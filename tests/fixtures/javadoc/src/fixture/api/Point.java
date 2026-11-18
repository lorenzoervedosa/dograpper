package fixture.api;

/**
 * A point on the grid.
 *
 * @param x the column
 * @param y the row
 */
public record Point(int x, int y) implements Comparable<Point> {

    /**
     * Orders points by row, then by column.
     *
     * @param other the point to compare with
     * @return a negative number, zero or a positive number
     */
    @Override
    public int compareTo(Point other) {
        return y != other.y ? Integer.compare(y, other.y) : Integer.compare(x, other.x);
    }
}
