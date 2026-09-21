// Shared category/era lists, so upload.html and admin.html can't drift
// apart on what the valid values are. Category order here is just picker
// order -- the frontend (app.js) figures out each category's actual room
// angle from what's in manifest.json, so adding a category here doesn't
// need any change there.
export const CATEGORIES = [
  { key: "Dinosaurs", emoji: "🦖", color: "#ff8a65" },
  { key: "Family", emoji: "👨‍👩‍👧‍👦", color: "#64b5f6" },
  { key: "Space", emoji: "🚀", color: "#9575cd" },
  { key: "Under the Sea", emoji: "🐠", color: "#4dd0e1" },
  { key: "Robots", emoji: "🤖", color: "#aed581" },
  { key: "Something Else", emoji: "✨", color: "#f06292" },
];

export const ERAS = ["Daycare", "Year 1", "Year 2", "Year 3", "Year 4"];
