# Bus Ticket Booking Agent

A Malaysia bus ticket booking system with AI-powered chat assistant. Built with FastAPI, Streamlit, PostgreSQL, and Ollama (local LLM).

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Chat App      │────▶│   FastAPI       │────▶│   PostgreSQL    │
│   (Streamlit)   │     │   (Backend)     │     │   (Database)    │
│   Port: 8470    │     │   Port: 7500    │     │   Port: 5432    │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
┌─────────────────┐              │              ┌─────────────────┐
│   Admin Panel   │              │              │   Ollama        │
│   (Streamlit)   │              └─────────────▶│   (Local LLM)   │
│   Port: 8501    │                             │   GPU-powered   │
└─────────────────┘                             └─────────────────┘
```

## Docker Components

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| **ollama** | `ollama` | - | Local LLM server (GPU-accelerated). Runs `llama3.2` for chat and `nomic-embed-text` for FAQ embeddings. |
| **postgres** | `bus_postgres` | 5432 | PostgreSQL database storing buses, routes, schedules, bookings, and payment info. |
| **streamlit** | `bus_admin` | 8501 | Admin panel for managing buses, routes, schedules, and viewing bookings with seat maps. |
| **chat** | `bus_chat` | 8470 | Customer-facing chat UI. Users can search buses, book tickets, and upload payment receipts. |
| **fastapi** | `bus_api` | 7500 | Backend API handling chat, bookings, payment verification, and FAQ retrieval (RAG). |

## Quick Start

### Prerequisites
- Docker & Docker Compose
- NVIDIA GPU with drivers installed (for Ollama)
- NVIDIA Container Toolkit

### 1. Clone and configure

```bash
git clone <repo-url>
cd bus_agent

# Create .env file (or edit existing)
cp .env.example .env
```

### 2. Configure environment variables

Edit `.env`:

```env
# Database
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=bus_booking

# LLM Model (must be compatible with Ollama)
OLLAMA_MODEL=
EMBEDDING_MODEL=
```

### 3. Start all services

```bash
docker compose up -d
```

First run will:
- Pull Ollama image and download LLM models (~4GB)
- Initialize PostgreSQL database
- Build FastAPI and Streamlit containers

### 4. Access the apps

| App | URL | Description |
|-----|-----|-------------|
| **Chat App** | http://localhost:8470 | Customer booking interface |
| **Admin Panel** | http://localhost:8501 | Manage buses, routes, schedules |
| **API Docs** | http://localhost:7500/docs | FastAPI Swagger UI |

### 5. Initial Setup (Admin Panel)

1. Open http://localhost:8501
2. Add a **Bank Account** (Settings > Bank Account) for payment verification
3. Add **Buses** with seat layouts
4. Add **Routes** between cities
5. Create **Schedules** (single, daily, or weekly)

## Features

- **AI Chat Assistant**: Natural language bus search and booking
- **Seat Selection**: Visual seat map with real-time availability
- **Payment Verification**: Upload receipt image, VLM extracts and verifies payment
- **FAQ System**: RAG-powered responses using ChromaDB
- **Multi-language**: English and Bahasa Malaysia support
- **Auto-cancel**: Unpaid bookings expire after 10 minutes

## Useful Commands

```bash
# View logs
docker compose logs -f fastapi
docker compose logs -f ollama

# Restart specific service
docker compose restart fastapi

# Stop all services
docker compose down

# Stop and remove volumes (reset database)
docker compose down -v

# Check Ollama models
docker exec ollama ollama list

# Pull additional model
docker exec ollama ollama pull llama3.2-vision
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | Chat with AI agent |
| `/schedules` | GET | Search bus schedules |
| `/schedules/{id}/seats` | GET | Get seat availability |
| `/bookings` | POST | Create booking |
| `/bookings/{id}` | GET | Get booking details |
| `/bookings/{id}` | DELETE | Cancel booking |
| `/bookings/{id}/receipt` | POST | Upload payment receipt |
| `/health` | GET | Health check |
| `/health/ollama` | GET | Check LLM status |

## Project Structure

```
bus_agent/
├── docker-compose.yml      # All services definition
├── .env                    # Environment variables
├── fastapi_app/            # Backend API
│   ├── main.py             # API endpoints
│   ├── agent.py            # LLM chat logic
│   ├── crud.py             # Database operations
│   ├── rag.py              # FAQ vector search
│   ├── vlm_service.py      # Vision model for receipts
│   └── faq/                # FAQ JSON files
├── chat_app/               # Customer chat UI
│   └── chat.py             # Streamlit chat interface
├── admin_panel/            # Admin dashboard
│   ├── admin.py            # Streamlit admin UI
│   └── database.py         # SQLAlchemy models
├── utils/                  # Shared utilities
│   └── seat_map_generator.py
└── scripts/
    └── ollama-entrypoint.sh  # Auto-pull LLM models
```

