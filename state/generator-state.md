# Generator State

## Iteration 1

### Completed Tasks
- TASK-001: Frontend framework (React + Vite + TailwindCSS) - completed in prior session
- TASK-002: Backend setup (Express + Prisma + SQLite) - completed this iteration

### Current State
- Frontend dev server: Running on port 3000
- Backend: Express + Prisma + SQLite with Socket.IO
- Database: SQLite at `server/prisma/dev.db`
- Prisma Client: Generated and synced

### Files Changed
- `ui/package.json` - Added "type": "module"
- `ui/vite.config.ts` - Configured server port to 3000
- `server/` - New backend directory with Express + Prisma + SQLite

### Backend API Endpoints
- `GET /api/health` - Health check
- `GET /api/users/:id` - Get user with pets, items, achievements
- `POST /api/users` - Create user
- `GET /api/classes/:id` - Get class with teacher and students
- `POST /api/classes` - Create class
- `GET /api/pets/:id` - Get pet with items
- `POST /api/pets` - Create pet
- `PATCH /api/pets/:id` - Update pet stats (real-time via Socket.IO)
- `POST /api/items/use` - Use item on pet
- `GET /api/tasks/:studentId` - Get student tasks
- `POST /api/tasks/:id/complete` - Complete task
- `GET /api/achievements` - List all achievements
- `POST /api/achievements/:id/unlock` - Unlock achievement

### Socket.IO Events
- `pet:update` - Emitted when pet stats change
- `subscribe:pet` / `unsubscribe:pet` - Pet state subscription

### Notes
- Backend server runs on port 3001
- Frontend dev server runs on port 3000
- WebSocket enables real-time pet state synchronization
