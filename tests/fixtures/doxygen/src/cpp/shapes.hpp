/**
 * @file shapes.hpp
 * @brief Boxes, the shapes they hold and the errors they raise.
 */
#ifndef FIXTURE_SHAPES_HPP
#define FIXTURE_SHAPES_HPP

#include <cstddef>
#include <utility>
#include <vector>

/// The largest number of items a box holds by default.
#define BOX_CAPACITY 16

/**
 * @brief Makes a box of ints from a list of items.
 *
 * The items are copied into the box in order.
 */
#define MAKE_BOX(...) ::shapes::Box<int>{__VA_ARGS__}

/// Shapes that fit in a box.
namespace shapes {

/// Why a box refused an item.
enum class BoxError {
    Full,   ///< The box already holds its limit.
    Sealed, ///< The box was sealed.
};

/// A point on the plane.
struct Point {
    double x; ///< Horizontal position.
    double y; ///< Vertical position.

    /// Where a point lies against a box.
    enum { Inside, Outside };

    /// The distance to another point.
    double distance(const Point& other) const;
};

/// The bits of a number, read as an integer or a float.
union Bits {
    unsigned long long integer; ///< The bits as an integer.
    double real;                ///< The bits as a float.
};

/// Anything with an area.
class Shape {
public:
    virtual ~Shape() = default;

    /// The area of the shape, in square units.
    virtual double area() const = 0;

    /**
     * @brief The name of the shape, for messages.
     *
     * @return the name, never empty
     */
    const char* name() const;
};

/// A square, the one shape a box is sure to hold.
class Square : public Shape {
public:
    /// A square of the given side.
    explicit Square(double side);

    /// The side times itself.
    double area() const override;

private:
    double side_;
};

/**
 * @brief A generic box that stores items in insertion order.
 *
 * Items keep their order; see put().
 *
 * @tparam T the item type
 * @tparam N the most items the box holds
 */
template <typename T, std::size_t N = BOX_CAPACITY>
class Box {
public:
    /// The type of the items.
    using value_type = T;

    /**
     * @brief The type of sizes and positions.
     *
     * Always unsigned, so a negative position cannot be written.
     */
    using size_type = std::size_t;

    /// How the box was closed.
    enum class Lid {
        Open,   ///< Items can still be put in.
        Closed, ///< No more items.
    };

    /// An empty box.
    Box();

    /**
     * @brief Stores one item.
     *
     * @param item the item to store
     * @return BoxError::Full when the box already holds N items.
     */
    BoxError put(const T& item);

    /**
     * @brief Stores one item, moving it in.
     *
     * @param item the item to move into the box
     * @return BoxError::Full when the box already holds N items.
     */
    BoxError put(T&& item);

    /// Stores every item of a range, in order.
    template <typename It>
    void put_all(It first, It last);

    /**
     * @brief Applies a function to every item.
     *
     * @tparam F the function type
     * @param f the function
     * @return a box of the results, in the same order
     *
     * @code
     * Box<int> ints;
     * auto doubled = ints.map([](int i) { return i * 2; });
     * @endcode
     */
    template <typename F>
    auto map(F f) const -> Box<decltype(f(std::declval<T>())), N>;

    /// The number of items.
    std::size_t size() const noexcept;

    /// Two boxes are equal when they hold equal items in the same order.
    bool operator==(const Box& other) const;

    /**
     * @brief The number of items.
     *
     * @deprecated Use size() instead.
     */
    std::size_t count() const noexcept;

    /**
     * @brief Two boxes differ when they are not equal.
     *
     * @param a one box
     * @param b the other box
     */
    friend bool operator!=(const Box& a, const Box& b) { return !(a == b); }

    /// A square may look inside any box.
    friend class Square;

    /// The most items any box of this type holds.
    static constexpr std::size_t limit = N;

    /**
     * @brief A view over the items of a box, converted on the fly.
     *
     * @tparam U the type the items are converted to
     */
    template <typename U>
    class View {
    public:
        /// The item at a position, converted to U.
        U at(std::size_t index) const;
    };

private:
    std::vector<T> items_;
};

/// A box of ints.
using IntBox = Box<int>;

/// The number of boxes made so far.
extern int boxes_made;

/**
 * @brief Makes a box that holds one item.
 *
 * @tparam T the item type
 * @param item the item
 * @return a box with item in it
 */
template <typename T>
Box<T> make_box(T item);

/**
 * @brief A box of points.
 *
 * Points are compared by position.
 * @relates Box
 */
using PointBox = Box<Point>;

}  // namespace shapes

/**
 * @brief Forgets every box made so far.
 *
 * Sets shapes::boxes_made back to zero.
 */
void reset_boxes();

namespace shapes {

/// Rules for comparing boxes without the shapes knowing.
namespace detail {

/// Whether two sizes fit in one box.
constexpr bool fits(std::size_t a, std::size_t b) noexcept;

}  // namespace detail

}  // namespace shapes

#endif
