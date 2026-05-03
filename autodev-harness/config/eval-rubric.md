# Evaluation Rubric for HelloSpace

## Scoring Scale
- 1-3: Broken, embarrassing, would not show anyone
- 4-5: Functional but clearly AI-generated
- 6: Decent but unremarkable
- 7: Good — junior developer's solid work
- 8: Very good — professional quality
- 9: Excellent — senior developer quality
- 10: Exceptional — could ship as real product

## Criteria

### Design Quality (weight: 0.3)
[Penalize]: Generic gradients, stock patterns, default themes, poor color contrast, inconsistent spacing
[Reward]: Cohesive palette (specific hex codes), distinctive typography (Inter font family), thoughtful 8px grid system, glass-morphism effects, custom iconography, responsive design across devices

### Originality (weight: 0.2)
[Penalize]: Template layouts, placeholder content, AI-slop aesthetics (e.g., #667eea → #764ba2 gradients), generic stock images
[Reward]: Custom decisions (e.g., unique card designs with glass effects), creative solutions to common problems, innovative features like integrated whiteboard+video

### Craft (weight: 0.3)
[Penalize]: Inconsistent spacing, broken responsiveness, missing states (loading/error/empty), jerky animations, poor typography hierarchy, lack of micro-interactions
[Reward]: Smooth animations (150ms ease-out transitions), pixel-perfect alignment, delightful hover effects, comprehensive states (loading skeletons, error messages, empty states with guides), accessibility support (WCAG 2.1 AA), polished shadows and borders

### Functionality (weight: 0.2)
[Penalize]: Broken features, missing error handling, edge case failures, slow performance, security vulnerabilities
[Reward]: All features work correctly (messages, video, docs, tasks, whiteboard), comprehensive validation (input sanitization, XSS prevention), graceful degradation (offline support for certain features), real-time performance < 100ms latency

## Additional Scoring Guidelines

### HelloSpace Specific Requirements

#### Video Quality (5% bonus)
- [Reward]: High-quality video with adaptive bitrate, noise cancellation, virtual backgrounds, smooth screen sharing
- [Penalize]: Pixelated video, laggy audio, broken screen sharing

#### Collaboration Features (5% bonus)
- [Reward]: Multi-user real-time editing, conflict resolution, presence indicators, @mentions, task references
- [Penalize]: Broken syncing, lost edits, missing presence indicators

#### Performance (5% penalty)
- [Penalize]: Slow load times, unresponsive UI, high memory usage, frequent crashes

#### Security (5% penalty)
- [Penalize]: Missing HTTPS, unencrypted data, hardcoded secrets, SQL injection vulnerabilities

## Pass Threshold: 7.0 / 10.0

## Acceptance Criteria
1. All 4 major features (Messages, Video, Docs, Tasks) must work
2. At least 3 minor features (Whiteboard, Rooms, Search, Notifications) must work
3. All quality gates must pass (lint, build, test)
4. No CRITICAL or HIGH severity security issues
5. GAN score must be >= 7.0

## Review Process
1. Evaluator reviews each feature according to rubric
2. Scores each dimension with explanations
3. Calculates weighted total
4. Provides specific feedback for improvement
5. If score < 7.0, returns to Generator with actionable feedback
