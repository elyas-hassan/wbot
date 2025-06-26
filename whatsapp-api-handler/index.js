const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios'); // For making HTTP requests to your Python bot

const app = express();
const port = 3000; // Port for your Node.js API server

// Middleware to parse JSON and URL-encoded bodies
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

// --- WhatsApp Client Setup ---
const client = new Client({
    authStrategy: new LocalAuth(), // Stores session in .wwebjs_auth folder
    puppeteer: {
        // Optional: run headless (no visible browser window)
        // headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox'], // Recommended for production environments
    }
});

client.on('qr', (qr) => {
    console.log('QR RECEIVED', qr);
    qrcode.generate(qr, { small: true });
    console.log('Scan the QR code above with your WhatsApp app.');
});

client.on('ready', () => {
    console.log('WhatsApp Client is ready!');
});

client.on('authenticated', () => {
    console.log('WhatsApp Client authenticated!');
});

client.on('auth_failure', msg => {
    console.error('AUTHENTICATION FAILURE', msg);
});

client.on('disconnected', (reason) => {
    console.log('WhatsApp Client disconnected!', reason);
    // Attempt to re-initialize or notify for manual restart
    // client.initialize(); // Auto-reinitialize (can sometimes help)
});

// --- API Endpoint to receive messages from WhatsApp and forward to Python ---
client.on('message', async msg => {
    // Log all incoming messages for debugging
    console.log(`[WhatsApp] Message from ${msg.from}: ${msg.body}`);

    // Forward message to your Python bot's endpoint
    try {
        // This is the endpoint your Python bot will expose to receive messages
        // Make sure your Python bot is running and listening on this URL
        await axios.post('http://localhost:5000/whatsapp-message', { // Python bot runs on port 5000
            from: msg.from,
            to: msg.to,
            body: msg.body,
            isGroup: msg.isGroup,
            timestamp: msg.timestamp,
            // Add other message properties as needed by your Python bot
        });
        console.log(`[API] Message forwarded to Python bot from ${msg.from}`);
    } catch (error) {
        console.error(`[API ERROR] Failed to forward message to Python bot: ${error.message}`);
    }
});

// --- API Endpoint for Python bot to send messages via WhatsApp ---
app.post('/send-message', async (req, res) => {
    const { to, message } = req.body; // 'to' can be JID (number@c.us) or group JID (number@g.us)
    if (!to || !message) {
        return res.status(400).json({ error: 'Recipient (to) and message are required.' });
    }
    try {
        // Ensure the JID format is correct if 'to' is just a number string
        let targetId = to;
        if (!to.includes('@')) { // Assume it's a number if no @ in it
            targetId = to + '@c.us'; // For private chat
            // Or you might need more complex logic to determine if it's group or private
            // For this example, if it's just a number, assume private
        }

        const chat = await client.getChatById(targetId); // Get the chat object
        if (chat) {
            await chat.sendMessage(message);
            console.log(`[API] Sent message to ${to}: ${message}`);
            res.status(200).json({ status: 'Message sent', to, message });
        } else {
            console.warn(`[API] Chat not found for ID: ${to}`);
            res.status(404).json({ error: 'Chat not found' });
        }

    } catch (error) {
        console.error(`[API ERROR] Error sending message to ${to}:`, error);
        res.status(500).json({ error: 'Failed to send message via WhatsApp', details: error.message });
    }
});

// --- Initialize WhatsApp Client ---
client.initialize();

// --- Start Express Server ---
app.listen(port, () => {
    console.log(`Node.js WhatsApp API handler listening on http://localhost:${port}`);
    console.log('Waiting for WhatsApp client to be ready...');
});