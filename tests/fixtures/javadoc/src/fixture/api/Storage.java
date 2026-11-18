package fixture.api;

import java.io.IOException;
import java.io.InputStream;

/**
 * Base class of every storage.
 */
public abstract class Storage {

    /** Name shown to the player. */
    protected String name;

    /**
     * Creates a storage with no name.
     */
    protected Storage() {
    }

    /**
     * Loads the storage state from a stream.
     *
     * @param input the stream to read
     * @param version the save format version
     * @throws IOException when the stream cannot be read
     */
    public void load(InputStream input, int version) throws IOException {
    }

    /**
     * Label of the storage.
     *
     * @return the name, or {@code "unnamed"}
     */
    public String label() {
        return name == null ? "unnamed" : name;
    }
}
