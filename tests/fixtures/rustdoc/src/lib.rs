//! Boxes, the errors they raise and the storage trait they share.
//!
//! # Usage
//!
//! ```
//! let mut b = fixture::Boxed::new();
//! b.put("apple").unwrap();
//! assert_eq!(b.len(), 1);
//! ```

use std::fmt;

pub mod shapes;

pub use shapes::Point;

/// The largest number of items a box holds.
pub const CAPACITY: usize = 16;

/// The number of boxes sealed so far.
pub static SEALED: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// Two values of one type.
pub type Pair<T> = (T, T);

/// A box of bytes.
pub type ByteBox = Boxed<u8>;

/// A generic box that stores items in insertion order.
///
/// Items keep their order; see [`Boxed::put`].
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Boxed<T> {
    /// The items, oldest first.
    pub items: Vec<T>,
    pub label: Option<String>,
    sealed: bool,
}

impl<T> Boxed<T> {
    /// The largest number of items one box holds.
    pub const LIMIT: usize = CAPACITY;

    /// Creates an empty box.
    pub const fn new() -> Self {
        Boxed { items: Vec::new(), label: None, sealed: false }
    }

    /// Stores one item.
    ///
    /// # Errors
    ///
    /// Returns [`BoxError::Full`] when the box already holds [`Self::LIMIT`] items.
    pub fn put(&mut self, item: T) -> Result<(), BoxError> {
        if self.sealed {
            return Err(BoxError::Sealed { since: 0 });
        }
        if self.items.len() >= Self::LIMIT {
            return Err(BoxError::Full);
        }
        self.items.push(item);
        Ok(())
    }

    /// Applies `f` to every item, keeping their order.
    pub fn map<U, F>(self, f: F) -> Boxed<U>
    where
        F: FnMut(T) -> U,
    {
        Boxed { items: self.items.into_iter().map(f).collect(), label: self.label, sealed: self.sealed }
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    /// Whether the box holds no item.
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// The number of items.
    #[deprecated(since = "0.2.0", note = "use `len` instead")]
    pub fn size(&self) -> usize {
        self.len()
    }
}

impl<T: Ord> Boxed<T> {
    /// Sorts the items in place.
    pub fn sort(&mut self) {
        self.items.sort();
    }
}

impl<T: fmt::Display> fmt::Display for Boxed<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} items", self.items.len())
    }
}

impl<T> Storage<usize> for Boxed<T> {
    type Item = T;

    fn get(&self, key: &usize) -> Option<&T> {
        self.items.get(*key)
    }
}

/// Why a box refused an item.
#[derive(Clone, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum BoxError {
    /// The box already holds its limit.
    Full,
    /// The box was sealed.
    Sealed {
        /// When it was sealed, in seconds since the epoch.
        since: u64,
    },
    Other(i32),
}

impl fmt::Display for BoxError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "box error")
    }
}

impl std::error::Error for BoxError {}

/// A keyed store of items.
pub trait Storage<K> {
    /// The stored item.
    type Item;

    /// The number of keys tried before giving up.
    const RETRIES: u32 = 3;

    /// Returns the item under `key`.
    fn get(&self, key: &K) -> Option<&Self::Item>;

    /// Whether an item is stored under `key`.
    fn contains(&self, key: &K) -> bool {
        self.get(key).is_some()
    }
}

impl<T> Storage<usize> for Vec<T> {
    type Item = T;

    fn get(&self, key: &usize) -> Option<&T> {
        <[T]>::get(self, *key)
    }
}

/// Applies `f` to both values of a pair.
pub fn apply<T, U, F>(pair: Pair<T>, mut f: F) -> Pair<U>
where
    F: FnMut(T) -> U,
{
    (f(pair.0), f(pair.1))
}

/// Applies `f` to the first value of a pair only.
#[deprecated(since = "0.2.0", note = "use `apply` instead")]
pub fn apply_first<T, F: FnOnce(T) -> T>(pair: Pair<T>, f: F) -> Pair<T> {
    (f(pair.0), pair.1)
}

/// Reads the bits as an integer.
///
/// # Safety
///
/// The bits must have been written as an integer.
pub unsafe fn read_int(bits: &Bits) -> u64 {
    bits.int
}

/// Makes a box from a list of items.
#[macro_export]
macro_rules! boxed {
    ($($item:expr),* $(,)?) => {{
        let mut b = $crate::Boxed::new();
        $(b.put($item).unwrap();)*
        b
    }};
}

/// The bits of a number, read as an integer or a float.
pub union Bits {
    /// As an integer.
    pub int: u64,
    /// As a float.
    pub float: f64,
}
