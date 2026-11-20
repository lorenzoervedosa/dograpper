//! Crate whose re-export makes rustdoc write a redirect stub.

mod imp {
    /// Merges two iterators.
    pub fn kmerge_by() {}
}

pub use imp::kmerge_by;
