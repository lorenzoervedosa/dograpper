//! A crate measured on nightly rustdoc.

/// Holds bytes.
pub struct Bag<T> {
    items: Vec<T>,
}

impl<T> Bag<T> {
    /// Takes the items out, one by one.
    pub fn drain_all(self) -> std::vec::IntoIter<T> {
        self.items.into_iter()
    }

    /// Number of items.
    pub fn len(&self) -> usize {
        self.items.len()
    }
}
