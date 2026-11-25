/**
 * @file ring.h
 * @brief A fixed-size ring buffer of bytes.
 *
 * A ring holds at most RING_SIZE bytes; ring_push() refuses a byte when it is full.
 */
#ifndef FIXTURE_RING_H
#define FIXTURE_RING_H

#include <stddef.h>

/**
 * @brief The number of bytes a ring holds.
 *
 * A power of two, so positions wrap with a mask.
 */
#define RING_SIZE 64

/// The larger of two sizes.
#define RING_MAX(a, b) ((a) > (b) ? (a) : (b))

/// What a ring operation did.
typedef enum ring_status {
    RING_OK,   /**< The operation succeeded. */
    RING_FULL, /**< The ring already holds RING_SIZE bytes. */
    RING_EMPTY /**< The ring holds no byte. */
} ring_status;

/// A ring buffer of bytes.
struct ring {
    unsigned char data[RING_SIZE]; /**< The bytes, in a circle. */
    size_t head;                   /**< Where the next byte is read. */
    size_t tail;                   /**< Where the next byte is written. */
};

/// Called once per byte by ring_visit().
typedef void (*ring_visitor)(unsigned char byte, void *ctx);

/**
 * @brief The number of rings initialised so far.
 *
 * ring_init() adds one; nothing ever subtracts.
 */
extern int ring_count;

/**
 * @brief Makes a ring empty.
 *
 * @param r the ring
 */
void ring_init(struct ring *r) { r->head = r->tail = 0; ring_count++; }

/**
 * @brief Stores one byte at the tail.
 *
 * @param r the ring
 * @param byte the byte to store
 * @return RING_FULL when the ring already holds RING_SIZE bytes, else RING_OK.
 */
ring_status ring_push(struct ring *r, unsigned char byte);

/**
 * @brief Calls a visitor on every byte, from head to tail.
 *
 * @param r the ring
 * @param visit the visitor
 * @param ctx passed to the visitor unchanged
 */
void ring_visit(const struct ring *r, ring_visitor visit, void *ctx);

/**
 * @brief Drops every byte.
 *
 * @param r the ring
 * @deprecated Use ring_init(), which does the same.
 */
void ring_clear(struct ring *r) { ring_init(r); }

#endif
