import sys
sys.path.insert(0, '.')

from app.geometry.contract import LineGeometry, Point2D, DirectionSemantics

# Test with diagonal line
diag_line = LineGeometry(
    p1=Point2D(0, 0),
    p2=Point2D(3840, 2160),
    direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
)

# Point above line (left side)
above = Point2D(1000, 200)
result_above = diag_line.side_of_point(above)
print(f"above point ({above.x}, {above.y}): side = {result_above}")
print(f"  vector: {diag_line.vector.to_tuple()}")
print(f"  point_vec: {(above.x - diag_line.p1.x, above.y - diag_line.p1.y)}")
line_vec = diag_line.vector
point_vec = above - diag_line.p1
cross = line_vec.cross(point_vec)
print(f"  cross product: {cross}")
print(f"  Expected: 1 (left/above side)")

# Point below line (right side)
below = Point2D(1000, 1000)
result_below = diag_line.side_of_point(below)
print(f"below point ({below.x}, {below.y}): side = {result_below}")

# Check what side the diagonal goes through
print()
print("Diagonal line goes from (0,0) to (3840, 2160)")
print("  This line has slope = 2160/3840 = 0.5625")
print("  At x=1000, y would be 562.5")
print("  So point (1000, 200) is ABOVE the diagonal line")
print("  Point (1000, 1000) is BELOW the diagonal line")

# The cross product of (p2-p1) x (point-p1) tells us which side
# If cross > 0, point is on left side of vector
# If cross < 0, point is on right side of vector
# If cross == 0, point is on the line
print()
print("For line from (0,0) to (3840,2160):")
print("  Vector = (3840, 2160)")
print("  At point (1000, 200):")
print(f"    Point vector = (1000, 200)")
print(f"    Cross = 3840*200 - 2160*1000 = {3840*200 - 2160*1000}")
print("    Cross < 0 means point is on RIGHT side of vector")
print()
print("  At point (1000, 1000):")
print(f"    Point vector = (1000, 1000)")
print(f"    Cross = 3840*1000 - 2160*1000 = {3840*1000 - 2160*1000}")
print("    Cross > 0 means point is on LEFT side of vector")
print()
print("The test expectations are WRONG!")
print("  'above' (1000, 200) is actually on the RIGHT side (cross < 0)")
print("  'below' (1000, 1000) is actually on the LEFT side (cross > 0)")