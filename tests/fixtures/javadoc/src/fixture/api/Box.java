package fixture.api;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;

/**
 * A generic box that stores comparable items.
 *
 * <p>Typical use:
 * <pre>{@code
 * Box<String> box = Box.of("apple");
 * box.put("pear");
 * }</pre>
 *
 * @param <T> the type of the stored items
 * @see Shelf
 */
public class Box<T extends Comparable<T>> extends Storage implements Shelf<T> {

    /** Most items a box can hold. */
    public static final int CAPACITY = 16;

    /** Items in insertion order. */
    private List<T> items;

    /**
     * Creates an empty box.
     */
    public Box() {
    }

    /**
     * Creates an empty box with a name.
     *
     * @param name the name of the box
     */
    public Box(String name) {
        this.name = name;
    }

    /**
     * Wraps one value in a new box.
     *
     * @param <U> the type of the value
     * @param value the value to wrap
     * @return a box holding {@code value}
     */
    public static <U extends Comparable<U>> Box<U> of(U value) {
        return new Box<>();
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public void put(T item) {
    }

    @Override
    public int size() {
        return 0;
    }

    /**
     * Groups the items by label.
     *
     * @return one map per group, keyed by label
     */
    public List<Map<String, T>> entries() {
        return List.of();
    }

    /**
     * Loads the box and its items.
     *
     * @param input the stream to read
     * @param version the save format version
     * @throws IOException when the stream cannot be read
     * @throws IllegalArgumentException when {@code version} is negative
     */
    @Override
    public void load(InputStream input, int version) throws IOException {
    }

    /**
     * Describes the box.
     *
     * @return the label and the item count
     */
    @Override
    public String toString() {
        return label() + ":" + size();
    }

    /**
     * Empties the box.
     *
     * @deprecated use {@link #put(Comparable)} with a new box instead
     */
    @Deprecated
    public void clear() {
    }

    public void shake(int times) {
    }

    /**
     * The lid of a box.
     */
    public static class Lid {

        /**
         * Tells whether the lid is closed.
         *
         * @return {@code true} when closed
         */
        public boolean isClosed() {
            return true;
        }
    }
}
