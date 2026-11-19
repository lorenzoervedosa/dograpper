//! Shapes that fit in a box.

use std::fmt;

/// A point on the plane.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Point {
    /// Horizontal position.
    pub x: i32,
    pub y: i32,
}

impl Point {
    /// The origin.
    pub const ORIGIN: Point = Point { x: 0, y: 0 };

    /// Returns the point moved by `dx` and `dy`.
    pub fn moved(self, dx: i32, dy: i32) -> Point {
        Point { x: self.x + dx, y: self.y + dy }
    }
}

/// A shape with an area.
pub trait Shape: fmt::Debug {
    /// The area of the shape.
    fn area(&self) -> f64;
}

/// A square, by the length of its side.
#[derive(Debug)]
pub struct Square(pub f64);

impl Shape for Square {
    fn area(&self) -> f64 {
        self.0 * self.0
    }
}
