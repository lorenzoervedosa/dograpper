// Topic (group) pages, one per \defgroup. Doxygen 1.9.8 documents a group's members on
// the group's page, with anchors that start with "g", under the names it writes for them:
// qualified for a namespace member, bare for a \relates one (as libstdc++'s make_shared).
// Named to sort after shapes.hpp: Doxygen numbers anonymous enums in input order, and an
// earlier one here would move the anchor of shapes::Point's.
#ifndef FIXTURE_TALLY_HPP
#define FIXTURE_TALLY_HPP

#include <cstddef>

/**
 * @defgroup algorithms Algorithms
 * @brief Functions over ranges of items, by topic.
 */

/**
 * @defgroup counting Counting
 * @ingroup algorithms
 * @brief Functions that count the items of a range.
 *
 * Each function walks its range once.
 */

/// Functions over ranges.
namespace algo {

/**
 * @ingroup counting
 * @brief A running count of items.
 */
class Tally {
public:
    /// The count so far.
    std::size_t total() const;
};

/**
 * @ingroup counting
 * @brief How a count treats items that compare equal.
 */
enum {
    COUNT_ALL,   ///< Every equal item counts.
    COUNT_FIRST, ///< Only the first equal item counts.
};

/**
 * @ingroup counting
 * @brief The number of items of a range equal to a value.
 *
 * @param first the start of the range
 * @param last the end of the range
 * @param value the value to look for
 * @return how many items compare equal to value
 */
template <typename It, typename T>
std::size_t count(It first, It last, const T& value);

/**
 * @ingroup counting
 * @brief The number of items of a range a predicate accepts.
 */
template <typename It, typename Pred>
std::size_t count_if(It first, It last, Pred pred);

/**
 * @relates Tally
 * @ingroup counting
 * @brief A tally that starts at a count.
 *
 * @param start the first count
 */
Tally make_tally(std::size_t start);

}  // namespace algo

#endif
