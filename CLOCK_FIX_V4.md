# MGR Global Records — Clock Fix v4

This version preserves the original orbital principle:

- The 12 hour planets have fixed positions on their orbit.
- Changing the active hour never changes a planet's `transform` or position.
- The active hour is shown only as a number on the corresponding planet, with a steady glow.
- The minute rocket is positioned on its minute orbit and remains on that orbit while its visual alternates between 🚀 and the current minute number every two seconds.
- Duplicate clock positioning code was removed so one clock loop owns the orbit positions.
- Jupiter, Saturn, Uranus and Neptune receive subtle attached rings.
- Earth remains stationary; its current CSS globe treatment is retained until a user-provided Earth sticker/asset is supplied.
