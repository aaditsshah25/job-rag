// Simple CORS Proxy for n8n webhook
const http = require('http');
const https = require('https');

const N8N_WEBHOOK_URL = 'https://aaditshah123.app.n8n.cloud/webhook/459a471a-f39f-42ea-b7e0-969e19b548f8';
const PORT = 3000;

const server = http.createServer((req, res) => {
    // Enable CORS for all origins
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    // Handle preflight OPTIONS request
    if (req.method === 'OPTIONS') {
        res.writeHead(200);
        res.end();
        return;
    }

    // Only handle POST requests to /webhook
    if (req.method === 'POST' && req.url === '/webhook') {
        let body = '';

        req.on('data', chunk => {
            body += chunk.toString();
        });

        req.on('end', () => {
            // Parse the incoming request
            const parsedUrl = new URL(N8N_WEBHOOK_URL);

            const options = {
                hostname: parsedUrl.hostname,
                path: parsedUrl.pathname + parsedUrl.search,
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(body)
                }
            };

            // Forward request to n8n
            const proxyReq = https.request(options, (proxyRes) => {
                let responseBody = '';

                proxyRes.on('data', chunk => {
                    responseBody += chunk;
                });

                proxyRes.on('end', () => {
                    // Return n8n response to frontend
                    res.writeHead(proxyRes.statusCode, {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    });
                    res.end(responseBody);
                });
            });

            proxyReq.on('error', (error) => {
                console.error('Proxy error:', error);
                res.writeHead(500, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: 'Proxy request failed', details: error.message }));
            });

            proxyReq.write(body);
            proxyReq.end();
        });
    } else {
        res.writeHead(404, { 'Content-Type': 'text/plain' });
        res.end('Not Found');
    }
});

server.listen(PORT, () => {
    console.log(`\n✅ CORS Proxy running on http://localhost:${PORT}`);
    console.log(`📡 Forwarding requests to: ${N8N_WEBHOOK_URL}`);
    console.log(`\nYour frontend should call: http://localhost:${PORT}/webhook\n`);
});
