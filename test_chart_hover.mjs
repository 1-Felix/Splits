import assert from "node:assert";
import { bandRects, cardPlace } from "./chart-hover.js";

// bandRects — even 3-point row over width 600
let b = bandRects([{ x: 100 }, { x: 300 }, { x: 500 }], 600, 150);
assert.strictEqual(b.length, 3);
assert.strictEqual(b[0].x, 0);                       // first band starts at edge
assert.strictEqual(b[0].w, 200);                     // boundary at midpoint (100+300)/2=200
assert.strictEqual(b[1].x, 200);
assert.strictEqual(b[1].w, 200);                     // 200..400
assert.strictEqual(b[2].x, 400);
assert.strictEqual(b[2].w, 200);                     // 400..600 reaches the edge
assert.strictEqual(b[0].y, 0);
assert.strictEqual(b[0].h, 150);

// bandRects — single point covers the whole width
b = bandRects([{ x: 42 }], 600, 30);
assert.deepStrictEqual(b, [{ x: 0, y: 0, w: 600, h: 30 }]);

// bandRects — empty
assert.deepStrictEqual(bandRects([], 600, 150), []);

// cardPlace — left zone, lower half -> anchor left, card above
let p = cardPlace(60, 120, 600, 150);
assert.strictEqual(p.anchorX, "left");               // 60/600 = 0.1 < 0.2
assert.strictEqual(p.place, "above");                // 120/150 = 0.8 >= 0.33
assert.strictEqual(p.leftPct, 10);
assert.strictEqual(p.topPct, 80);

// cardPlace — right zone, near top -> anchor right, card below
p = cardPlace(540, 20, 600, 150);
assert.strictEqual(p.anchorX, "right");              // 540/600 = 0.9 > 0.8
assert.strictEqual(p.place, "below");                // 20/150 = 0.133 < 0.33

// cardPlace — middle zone -> centered
p = cardPlace(300, 75, 600, 150);
assert.strictEqual(p.anchorX, "center");

console.log("ALL PASS");
