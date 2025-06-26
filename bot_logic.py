from flask import Flask, request, jsonify
import requests
import json
import os
from datetime import datetime, timedelta # <-- ADDED timedelta here
import threading
import time
import re

app = Flask(__name__)

# --- Configuration ---
NODEJS_API_URL = 'http://localhost:3000'
TASKS_FILE = 'tasks.json'
ARCHIVE_TASKS_FILE = 'archive_tasks.json'
TARGET_JID_FOR_REPLIES = 'YOUR_WHATSAPP_JID_FOR_REPLIES' # <-- REPLACE THIS!

# --- Task Storage ---
def load_tasks(file_path):
    if not os.path.exists(file_path):
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            tasks_data = json.load(f)
            for task in tasks_data:
                if isinstance(task['date'], str):
                    task['date'] = datetime.fromisoformat(task['date'])
            return tasks_data
        except json.JSONDecodeError:
            print(f"Error decoding {file_path}. Starting with empty tasks.")
            return []
        except KeyError:
            print(f"KeyError in {file_path}. Tasks might be malformed. Starting with empty tasks.")
            return []

def save_tasks(tasks, file_path):
    tasks_to_save = []
    for task in tasks:
        task_copy = task.copy()
        task_copy['date'] = task_copy['date'].isoformat()
        tasks_to_save.append(task_copy)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(tasks_to_save, f, indent=4, ensure_ascii=False)

# NEW HELPER FUNCTION: Get next available sequential ID
def get_next_task_id():
    active_tasks = load_tasks(TASKS_FILE)
    archived_tasks = load_tasks(ARCHIVE_TASKS_FILE)
    
    all_tasks = active_tasks + archived_tasks
    
    if not all_tasks:
        return 1
    
    max_id = 0
    for task in all_tasks:
        try:
            task_id_int = int(task['id'])
            if task_id_int > max_id:
                max_id = task_id_int
        except ValueError:
            continue 
            
    return max_id + 1

# --- Communication with Node.js API ---
def send_whatsapp_message(recipient_jid, message_text):
    payload = {
        'to': recipient_jid,
        'message': message_text
    }
    try:
        response = requests.post(f"{NODEJS_API_URL}/send-message", json=payload)
        response.raise_for_status()
        print(f"[Python] Sent message to {recipient_jid}: '{message_text}' (Response: {response.status_code})")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[Python ERROR] Failed to send message to {recipient_jid} via Node.js API: {e}")
        return None

# --- WhatsApp Message Receiver Endpoint ---
@app.route('/whatsapp-message', methods=['POST'])
def receive_whatsapp_message():
    data = request.json
    sender_jid = data.get('from')
    message_body = data.get('body')
    is_group = data.get('isGroup')
    chat_id = data.get('to')

    print(f"[Python] Received message from {sender_jid} (in chat {chat_id}): {message_body}")

    message_lower = message_body.lower()
    tasks = load_tasks(TASKS_FILE)
    
    reply_to_jid = sender_jid 
    if is_group:
        reply_to_jid = chat_id 

    # !add <title> on <YYYY-MM-DD HH:MM>
    if message_lower.startswith('!add '):
        match = re.match(r'!add\s+(.+)\s+on\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})$', message_body, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            date_str = match.group(2).strip()
            try:
                task_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
                if task_date < datetime.now():
                    send_whatsapp_message(reply_to_jid, "Cannot schedule a task in the past. Please provide a future date and time.")
                else:
                    new_sequential_id = get_next_task_id()
                    tasks.append({'id': str(new_sequential_id), 'title': title, 'date': task_date, 'sent': False})
                    save_tasks(tasks, TASKS_FILE)
                    send_whatsapp_message(reply_to_jid, f"✅ Task '{title}' scheduled for {task_date.strftime('%Y-%m-%d %H:%M')}. (ID: {new_sequential_id})")
            except ValueError:
                send_whatsapp_message(reply_to_jid, "Invalid date format. Please use `YYYY-MM-DD HH:MM`. Example: !add Call Mom on 2025-12-25 10:00")
        else:
            send_whatsapp_message(reply_to_jid, "Usage: !add <title> on <YYYY-MM-DD HH:MM>. Example: !add Call Mom on 2025-12-25 10:00")

    # !schedule or s
    elif message_lower == '!schedule' or message_lower == 's':
        if not tasks:
            send_whatsapp_message(reply_to_jid, "No active tasks scheduled.")
        else:
            tasks.sort(key=lambda x: x['date'])
            response_lines = ["🗓️ Your Active Schedule:\n"]
            for task in tasks:
                status = ""
                if task['date'] < datetime.now():
                    status = " (⌛ Overdue)"
                response_lines.append(f"*{task['id']}*. {task['title']}")
                response_lines.append(f"  _Due:_ {task['date'].strftime('%Y-%m-%d %H:%M')}{status}\n")
            send_whatsapp_message(reply_to_jid, "\n".join(response_lines))
    
    # !delete <ID> (using sequential ID for deletion)
    elif message_lower.startswith('!delete '):
        try:
            task_id_to_delete = message_lower.split(' ')[1].strip()
            
            task_to_delete_obj = None
            for task in tasks:
                if task['id'] == task_id_to_delete:
                    task_to_delete_obj = task
                    break

            if task_to_delete_obj:
                tasks_before_delete = len(tasks)
                tasks = [task for task in tasks if task['id'] != task_id_to_delete]
                save_tasks(tasks, TASKS_FILE)
                if len(tasks) < tasks_before_delete:
                    send_whatsapp_message(reply_to_jid, f"Task '{task_to_delete_obj['title']}' (ID: {task_id_to_delete}) deleted successfully.")
                else:
                     send_whatsapp_message(reply_to_jid, f"Failed to delete task with ID {task_id_to_delete}. It might have been already deleted.")
            else:
                send_whatsapp_message(reply_to_jid, f"Task with ID '{task_id_to_delete}' not found in active schedule.")

        except IndexError:
            send_whatsapp_message(reply_to_jid, "Usage: !delete <task_id>. Example: !delete 1")
        except Exception as e:
            send_whatsapp_message(reply_to_jid, f"Error deleting task: {e}")

    # !archive or a (to view archived tasks)
    elif message_lower == '!archive' or message_lower == 'a':
        archived_tasks = load_tasks(ARCHIVE_TASKS_FILE)
        if not archived_tasks:
            send_whatsapp_message(reply_to_jid, "No tasks in archive.")
        else:
            archived_tasks.sort(key=lambda x: x['date'])
            response_lines = ["🗄️ Your Archived Tasks:\n"]
            for task in archived_tasks:
                response_lines.append(f"*{task['id']}*. {task['title']}")
                response_lines.append(f"  _Due:_ {task['date'].strftime('%Y-%m-%d %H:%M')}\n")
            send_whatsapp_message(reply_to_jid, "\n".join(response_lines))

    return jsonify({'status': 'Message received and processed'}), 200

# --- Alert Checker (Runs in a separate thread) ---
def alert_checker():
    while True:
        time.sleep(10) # Check every 10 seconds for alerts
        current_time = datetime.now() # Get current time once for consistency in this loop
        print(f"[ALERT_CHECKER] Running at {current_time}") # NEW DEBUG
        
        active_tasks = load_tasks(TASKS_FILE)
        archived_tasks = load_tasks(ARCHIVE_TASKS_FILE)

        tasks_to_keep = [] # Tasks that are not yet due/sent
        
        for task in active_tasks:
            # Calculate the time 5 minutes from now
            five_minutes_from_now = current_time + timedelta(minutes=5) # Ensure timedelta is imported

            print(f"[ALERT_CHECKER] Checking task ID {task['id']} ('{task['title']}')...")
            print(f"  Due: {task['date']}")
            print(f"  Sent: {task['sent']}")
            print(f"  Current Time: {current_time}")
            print(f"  5 Mins From Now: {five_minutes_from_now}")
            print(f"  Is not sent? {not task['sent']}")
            print(f"  Is due <= current time? {task['date'] <= current_time}") # Original condition
            print(f"  Is due <= 5 mins from now? {task['date'] <= five_minutes_from_now}") # New condition

            # Condition to send alert: not sent AND (due now OR due within next 5 minutes)
            if not task['sent'] and (task['date'] <= current_time or task['date'] <= five_minutes_from_now):
                print(f"[Python] Triggering alert for task ID {task['id']}: {task['title']}")
                
                # Check if the message actually sends
                response = send_whatsapp_message(TARGET_JID_FOR_REPLIES, f"🔔 REMINDER: *{task['title']}*\n  _Scheduled for:_ {task['date'].strftime('%Y-%m-%d %H:%M')}")
                
                if response: # Only mark as sent and archive if message was successfully sent via API
                    task['sent'] = True
                    archived_tasks.append(task)
                    print(f"[Python] Task ID {task['id']} moved to archive after successful send.")
                else:
                    print(f"[Python WARNING] Alert for ID {task['id']} failed to send. Not archiving yet.")
                    tasks_to_keep.append(task) # Keep it in active if send failed

            else: # Task is not yet due, or already sent, or doesn't meet the 5-min window
                tasks_to_keep.append(task)

        # Save the updated lists
        save_tasks(tasks_to_keep, TASKS_FILE)
        save_tasks(archived_tasks, ARCHIVE_TASKS_FILE)

if __name__ == "__main__":
    print(f"Python bot listening on http://localhost:5000 (Target JID: {TARGET_JID_FOR_REPLIES})")
    alert_thread = threading.Thread(target=alert_checker)
    alert_thread.daemon = True
    alert_thread.start()
    app.run(port=5000, debug=False)