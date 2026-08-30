Update the current Figma design of the AI Attendance Command Center.

IMPORTANT:
The real project currently uses TWO cameras only.

Replace ALL references to 6 cameras with exactly TWO cameras.

DO NOT redesign the entire interface from scratch.
Preserve the current visual language, layout quality, components, interactions,
Liquid Glass design system, morphism, ambient lighting, typography, spacing,
animations, and information hierarchy.

==================================================
CAMERA CONFIGURATION
==================================================

The system must visually represent ONLY:

CAM1
CAM2

Never display:

CAM3
CAM4
CAM5
CAM6

Do not show "6-camera grid".

The primary Live Command Center should use a clean TWO-CAMERA layout.

Preferred layout:

┌──────────────────────────────────────────────────────┐
│ AI ATTENDANCE COMMAND CENTER              ● LIVE     │
├───────────────────────────────┬──────────────────────┤
│                               │                      │
│            CAM1               │     ATTENDANCE       │
│                               │                      │
│      AI detection overlay     │   Present / Late     │
│                               │   Left / Absent      │
│                               │                      │
├───────────────────────────────┤                      │
│                               │                      │
│            CAM2               │     LIVE EVENTS      │
│                               │                      │
│      AI detection overlay     │     Event stream     │
│                               │                      │
└───────────────────────────────┴──────────────────────┘

Make the two camera feeds large and visually dominant.

CAM1 and CAM2 must have equal visual importance.

==================================================
LIVE COMMAND CENTER
==================================================

Change:

"6-camera grid"

to:

"Dual-camera command center"

Show exactly:

- CAM1
- CAM2

Each camera card should retain:

- AI bounding boxes
- corner-bracket overlays
- person identity labels
- confidence
- identity certainty
- track ID
- camera status
- LIVE indicator
- loading state
- degraded state
- offline state
- retry action

Do not add extra camera cards merely to fill empty space.

Use the available space to make CAM1/CAM2 larger and easier to inspect.

==================================================
ATTENDANCE PANEL
==================================================

Keep:

- Present
- Late
- Left
- Absent
- Total

Make this panel visually secondary to the two camera feeds.

Use clear semantic colors and strong typography.

==================================================
LIVE EVENT TIMELINE
==================================================

Keep the event stream.

Events should reference only:

CAM1
CAM2

Example:

CAM1 · HS001 · IN
CAM2 · HS004 · OUT
CAM1 · HS017 · CROSSING

Use JetBrains Mono for:

- timestamps
- camera IDs
- track IDs
- global observation IDs
- event IDs

==================================================
PERSON SEARCH
==================================================

Keep the Person Search screen unchanged in functionality.

Do NOT introduce additional cameras.

Person appearance history may contain:

CAM1
CAM2

Only.

==================================================
PERSON DETAIL
==================================================

Keep:

- identity card
- confidence
- face quality
- attendance state
- provenance
- appearance history
- replay
- technical metadata

Per-camera statistics must contain exactly:

CAM1
CAM2

Do NOT create six-camera charts.

==================================================
ANNOTATED REPLAY
==================================================

Keep the replay design.

Camera selector must contain:

CAM1
CAM2

Replay annotations must reference only these cameras.

Preserve:

- detection bounding boxes
- track IDs
- identity labels
- confidence
- event markers
- scrubber
- playback controls
- speed selector
- provenance action

==================================================
PROVENANCE CHAIN
==================================================

Keep the existing provenance visualization.

It should remain independent of the number of cameras.

When camera information appears, valid values are:

CAM1
CAM2

Do not add camera nodes for CAM3-CAM6.

Keep:

- SHA-256 hashes
- verification badges
- technical metadata
- expandable nodes
- raw attestation JSON

==================================================
ENROLLMENT / ARCFACE DATABASE
==================================================

Keep the four-step enrollment flow:

1. Identity
2. Face Capture
3. Embedding Checks
4. Confirm

Keep:

- face quality
- embedding status
- enrollment state
- person ID
- database status

Do not associate enrollment with six cameras.

Enrollment is identity-centric, not camera-centric.

==================================================
VISUAL DESIGN
==================================================

Preserve and enhance the existing:

- Liquid Glass
- subtle Morphism
- dark cinematic background
- ambient cyan/violet lighting
- glass depth
- soft shadows
- pulse-ring status indicators
- confidence bars
- skeleton shimmer
- corner-bracket camera overlays
- smooth hover interactions
- button micro-interactions
- elegant loading screens
- empty states
- error states

Do NOT add excessive decoration.

The UI should feel like a professional AI operations console.

==================================================
RESPONSIVE BEHAVIOR
==================================================

Desktop:

CAM1 + CAM2 should remain the primary visual focus.

Tablet:

CAM1
CAM2

stack cleanly if necessary.

Mobile:

CAM1
CAM2

should become a vertical sequence.

Do not shrink six nonexistent camera cards into unusable thumbnails.

==================================================
IMPORTANT CONSTRAINT
==================================================

The real AI Attendance system currently operates with TWO cameras.

The UI must visually and semantically reflect that architecture.

Do NOT describe the system as:

"6-camera"
"6-camera grid"
"N-camera live dashboard"

For this UI:

"Dual-Camera AI Attendance Command Center"

is the correct presentation.

==================================================
FINAL QUALITY CHECK
==================================================

Verify every screen after the change:

✓ Live Command Center → exactly CAM1 + CAM2
✓ Person Search → no extra cameras
✓ Person Detail → only CAM1/CAM2
✓ Annotated Replay → CAM1/CAM2 selector only
✓ Provenance → CAM1/CAM2 references only
✓ Enrollment → camera-independent
✓ No CAM3/CAM4/CAM5/CAM6 anywhere
✓ Existing Liquid Glass design preserved
✓ Existing Morphism preserved
✓ Existing animations preserved
✓ Existing typography preserved
✓ Existing responsive behavior preserved
✓ Information hierarchy remains clear

Do not change backend architecture.

Do not invent additional cameras.

Do not remove existing functionality.

Only adapt the current Figma design from a six-camera concept to the
actual TWO-CAMERA AI Attendance system while using the freed visual space
to make the interface more premium, readable, spacious, and impressive.