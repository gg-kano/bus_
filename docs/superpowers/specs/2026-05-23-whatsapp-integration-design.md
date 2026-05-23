# WhatsApp Integration Design

**Date:** 2026-05-23  
**Status:** Approved  

## Summary

Replace the Streamlit chat frontend with a WhatsApp Business bot. Users interact with the BusGo booking agent via WhatsApp instead of a web UI. The existing FastAPI backend is unchanged.

## Architecture

```
User's WhatsApp → Meta Cloud API → Webhook POST
                                        ↓
                              whatsapp_app (FastAPI, port 8080)
                                        ↓
                              fastapi_app (port 7500)
                              ├── /auth/login   (auto-register by phone)
                              ├── /chat         (AI agent)
                              └── /bookings/{id}/receipt  (payment photo)
                                        ↓
                              PostgreSQL + Ollama
```

The `chat_app/` Streamlit service is removed from `docker-compose.yml`.  
A new `whatsapp_app/` service is added.

## Components

### whatsapp_app/main.py

A FastAPI app with two routes:

- `GET /webhook` — Webhook verification endpoint. Meta calls this once with a `hub.challenge` to confirm the server. Responds with the challenge if `hub.verify_token` matches `WEBHOOK_VERIFY_TOKEN`.
- `POST /webhook` — Receives all incoming WhatsApp messages from Meta.

**On text message:**
1. Extract sender phone number
2. First message → POST `/auth/login` with `{name: phone, phone: phone}` to auto-register
3. POST `/chat` with `{message, session_id: phone, passenger_id}`
4. Send reply text back via PyWa

**On image message (payment receipt):**
1. Bot checks session for `pending_receipt_booking_id`
2. If no booking ID in context → reply asking for booking ID
3. Once booking ID known → download image from Meta CDN → POST `/bookings/{id}/receipt`
4. Reply with verification result

### Session State (in-memory TTLDict, 30 min TTL)

Per phone number:
- `passenger_id` — set after auto-login
- `pending_receipt_booking_id` — set when awaiting receipt attachment

### New Files

```
whatsapp_app/
├── main.py
├── requirements.txt   # pywa, httpx, python-dotenv
└── Dockerfile
```

## Environment Variables

```env
WHATSAPP_TOKEN=<meta_access_token>
WHATSAPP_PHONE_NUMBER_ID=<phone_number_id>
WEBHOOK_VERIFY_TOKEN=<any_secret_string_you_choose>
FASTAPI_URL=http://fastapi:7500
```

## Deployment

### Local development
1. Run `docker compose up`
2. Run `ngrok http 8080` → get public HTTPS URL
3. Set webhook URL in Meta Developer Console → WhatsApp > Configuration

### Production
1. Deploy to VPS with public IP + SSL (Caddy/nginx + Let's Encrypt)
2. Set real domain as webhook URL in Meta console
3. Apply for official WhatsApp Business number verification

## Constraints & Limitations

- Meta test token expires ~24 hours; a permanent System User token is needed for production
- The test number (+1 555 648-5135) can only message pre-approved recipients; production requires business verification
- Webhook URL must be HTTPS (ngrok provides this for local dev)
- Meta webhook POST must receive HTTP 200 within 20 seconds; processing is async
- Seat map images cannot be sent via WhatsApp in this design — seat selection is text-only ("Reply with seat number: 1A, 2B, etc.")
- As of 2026, task-specific bots (booking/support) are allowed; general-purpose AI bots are not
