# HelloSpace - Immersive Team Collaboration Platform

## Vision

HelloSpace is an immersive collaboration platform designed for remote teams, seamlessly integrating video conferencing, real-time documents, task management, and creative whiteboards into a single cohesive experience. Our target users are design teams, product teams, and startups who want more than just chat—they want a warm, high-quality space where creativity naturally flows.

## Design Direction

### Visual System
- **Color Palette**:
  - Primary: `#2563eb` (Professional Blue)
  - Secondary: `#7c3aed` (Creative Purple)
  - Accent: `#f59e0b` (Energetic Amber)
  - Backgrounds: `#f8fafc` (Main), `#ffffff` (Cards)
  - Text: `#0f172a` (Headings), `#475569` (Body), `#94a3b8` (Secondary)
  - Success: `#10b981`, Error: `#ef4444`, Warning: `#f59e0b`

- **Typography**:
  - Display: Inter Bold (700) - 32px, 28px, 24px
  - Heading: Inter SemiBold (600) - 20px, 18px
  - Body: Inter Regular (400) - 16px, 14px
  - Monospace: JetBrains Mono - 14px (Code blocks)

- **Layout Philosophy**: 8px grid system, comfortable spacing (16px, 24px, 32px increments), three-column primary layout, balanced information density that's neither too crowded nor too sparse.

- **Visual Identity**:
  - Subtle glass-morphism effects (backdrop-filter: blur(12px))
  - Thoughtfully designed shadow system (3 depth levels)
  - Smooth micro-animations (150ms ease-out transitions on hover)
  - Custom iconography instead of generic icon sets
  - Fade-in/fade-out transitions between states

- **Anti-Patterns to Avoid**:
  - ❌ Generic gradient backgrounds (#667eea → #764ba2)
  - ❌ Stock placeholder images
  - ❌ Default UI library themes
  - ❌ Template layouts
  - ❌ Missing loading/error/empty states

## Features (14 total)

### Must-Have (Sprint 1-2)

1. **Instant Messaging with Threads**: Users can send text, emojis, files, with support for message replies and threaded discussions
   - Acceptance: Real-time message delivery, typing indicators, unread counts, thread expansion/collapse

2. **High-Quality Video Conferencing**: 1-8 participant video calls with screen sharing, virtual backgrounds, and noise cancellation
   - Acceptance: Adaptive video grid, noise cancellation, quality metrics display, recording functionality

3. **Real-Time Collaborative Documents**: TipTap/ProseMirror block-based editor with multi-user editing and version history
   - Acceptance: Rich text editing, @mentions, image/table insertion, change tracking, 30-day history

4. **Task Management Board**: Drag-and-drop Kanban with task cards, priority labels, and deadline reminders
   - Acceptance: Multiple boards, task assignments, progress indicators, deadline calendar, drag sorting

5. **Creative Whiteboard**: Infinite canvas with drawing tools, sticky notes, and multi-user collaboration
   - Acceptance: Multiple brush styles/colors, shape alignment guides, canvas zoom, PNG export

6. **Team Member Management**: Invites, role-based permissions, presence indicators, and profile pages
   - Acceptance: Role permissions (Admin/Member/Viewer), real-time presence updates, profile editing

7. **Notifications Center**: Aggregated notifications with mark-as-read, archiving, and preference settings
   - Acceptance: Categorized notifications, bulk actions, mute toggles, desktop notification permissions

### Should-Have (Sprint 3-4)

8. **Voice Rooms (Persistent Channels)**: Continuous voice channels like Discord for lightweight ongoing communication
   - Acceptance: Join/leave rooms, volume controls, voice activity detection, channel categorization

9. **File Management Library**: Team file storage with folder organization, version control, and share links
   - Acceptance: Drag-and-drop upload, file previews, version history, share links with expiration

10. **Calendar & Scheduling**: Calendar view, meeting booking, reminders, and Zoom/Meet integration
    - Acceptance: Week/month views, recurring meetings, reminder push, auto-generated meeting links

11. **Search & Archiving**: Full-text search across messages, docs, tasks with advanced filters
    - Acceptance: Keyword highlighting, filters (type/date/author), search history, archived access

### Nice-to-Have (Sprint 5+)

12. **Integrations Marketplace**: Slack, GitHub, Figma, Jira integrations
    - Acceptance: Integration listing, OAuth connection, configuration UI, activity logs

13. **Analytics & Insights**: Team activity tracking, collaboration pattern analysis, productivity reporting
    - Acceptance: Dashboard visualizations, data export, custom date ranges, trend comparisons

14. **Custom Theme System**: Team-customizable colors, logos, welcome pages
    - Acceptance: Theme editor, logo upload, preview mode, CSS variable export

## User Flows

### Flow 1: Team Morning Standup
1. Members click "Morning Standup" voice room to join
2. View "Today's Tasks" column on the Kanban board
3. Each person updates their task status on the board
4. Start video call for any items needing discussion
5. Collaboratively edit "Today's Notes" document during call
6. Leave room when done, system logs call duration automatically

### Flow 2: Design Review Session
1. Designer creates new whiteboard, imports Figma screenshots
2. Invites team to the whiteboard session
3. Use pen tools and sticky notes to provide feedback directly on canvas
4. Start video call for real-time discussion
5. Export feedback as task cards to the Kanban board
6. Save whiteboard and generate share link

### Flow 3: Collaborative Document Work
1. PM creates new "Product Requirements" document
2. @mentions designer and lead developer
3. Team edits in real-time, adds inline comments
4. Inserts task cards referencing board items
5. Views version history, restores previous version if needed
6. Marks document as "Reviewed" when complete

## Technical Stack

### Frontend
- **Framework**: React 18 + TypeScript 5
- **State Management**: Zustand (lightweight) + React Query (server state)
- **Styling**: Tailwind CSS 4 + Radix UI (headless components)
- **Real-Time**: Socket.IO client (WebSocket)
- **Video**: LiveKit WebRTC SDK
- **Rich Text**: TipTap (ProseMirror wrapper)
- **Whiteboard**: Fabric.js + custom collaboration layer
- **Routing**: React Router v6
- **Icons**: Phosphor Icons (curated subset)

### Backend
- **Framework**: NestJS 10 + TypeScript
- **Database**: PostgreSQL 16 + Prisma ORM
- **Real-Time**: Socket.IO + Redis adapter (horizontal scaling)
- **Auth**: JWT + bcrypt (password hashing)
- **Storage**: S3-compatible object storage (MinIO for dev)
- **Video**: LiveKit server (self-hosted or managed)
- **Search**: Elasticsearch (or MeiliSearch for lighter footprint)
- **Queue**: BullMQ (background jobs)

### DevOps
- **Build**: Vite (frontend) + tsc (backend)
- **Testing**: Vitest + Playwright
- **Linting**: ESLint + Prettier
- **Container**: Docker + Docker Compose
- **CI/CD**: GitHub Actions

## Edge Cases to Handle

- **Empty States**: Each feature module has customized empty states with guidance and examples
- **Error States**: Friendly error messages, retry buttons, offline mode for network disconnects
- **Loading States**: Skeleton loading, progress bars, optimistic updates (UI updates first, then waits for confirmation)
- **Long Content**: Message/document collapse/expand, virtual scrolling, lazy loading
- **Special Characters**: Full Unicode support, safe XSS prevention, Markdown rendering
- **Slow Networks**: Request timeout with retry, data caching, offline-first architecture
- **Concurrent Edits**: CRDT algorithm for conflict resolution, editing state locks, version conflict handling

## Success Metrics

- Cold start load time < 2 seconds
- Message latency < 100ms
- Video call latency < 150ms
- No noticeable conflicts during multi-user collaboration
- 60fps page responsiveness
- WCAG 2.1 AA accessibility support

---

*Last Updated: 2026-05-03*
