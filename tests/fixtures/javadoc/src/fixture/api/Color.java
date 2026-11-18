package fixture.api;

/**
 * Colors a box can be painted.
 */
public enum Color {
    /** The default color. */
    RED,
    GREEN,
    /** A rare color. */
    BLUE;

    /**
     * Mixes this color with another one.
     *
     * @param other the color to mix with
     * @return the mixed color
     */
    public Color mix(Color other) {
        return this;
    }
}
