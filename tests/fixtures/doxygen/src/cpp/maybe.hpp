// Overloads that differ only in the default template argument of an enable_if
// constraint, as libstdc++ 13's std::optional and std::pair declare them:
// Doxygen 1.9.8 gives each pair one anchor.
#ifndef FIXTURE_MAYBE_HPP
#define FIXTURE_MAYBE_HPP

#include <type_traits>

/// Values that may be missing.
namespace maybe {

/// A value of type T, or none.
template <typename T>
class Maybe {
public:
    /// An empty maybe.
    Maybe() noexcept;

    /// Holds a value that converts to T implicitly.
    template <typename U = T, std::enable_if_t<std::is_convertible_v<U, T>, bool> = true>
    Maybe(U&& value);

    /// Holds a value that converts to T only explicitly.
    template <typename U = T, std::enable_if_t<!std::is_convertible_v<U, T>, bool> = false>
    explicit Maybe(U&& value);

    /**
     * @brief Replaces the value with one that converts to T implicitly.
     *
     * @param value the new value
     * @return this maybe
     */
    template <typename U = T, std::enable_if_t<std::is_convertible_v<U, T>, bool> = true>
    Maybe& operator=(U&& value);

    /**
     * @brief Replaces the value with one that converts to T only explicitly.
     *
     * @param value the new value, converted with a cast
     * @return this maybe
     */
    template <typename U = T, std::enable_if_t<!std::is_convertible_v<U, T>, bool> = false>
    Maybe& operator=(U&& value);

    /// Whether a value is held.
    bool has_value() const noexcept;
};

}  // namespace maybe

#endif
