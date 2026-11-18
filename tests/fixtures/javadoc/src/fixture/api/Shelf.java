package fixture.api;

/**
 * A shelf that holds items of one type.
 *
 * @param <T> the type of the items on the shelf
 */
public interface Shelf<T> {

    /**
     * Puts an item on the shelf.
     *
     * @param item the item to put
     * @throws IllegalStateException when the shelf is full
     */
    void put(T item);

    /**
     * Counts the items on the shelf.
     *
     * @return the number of items
     */
    int size();

    /**
     * Tells whether the shelf holds no item.
     *
     * @return {@code true} when {@link #size()} is zero
     */
    default boolean isEmpty() {
        return size() == 0;
    }
}
