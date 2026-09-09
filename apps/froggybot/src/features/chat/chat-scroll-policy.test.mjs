import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldFollowLatest } from './chat-scroll-policy.ts';

const position = (offset, contentHeight = 2000, viewportHeight = 600) => ({ offset, contentHeight, viewportHeight });

test('wheel, drag, or keyboard scrolling upward releases auto-follow', () => {
  assert.equal(shouldFollowLatest(true, position(1400), position(1380)), false);
  assert.equal(shouldFollowLatest(true, position(1400), position(800)), false);
});

test('new content and polling do not detach a reader already following the bottom', () => {
  assert.equal(shouldFollowLatest(true, position(1400), position(1400, 2600)), true);
  assert.equal(shouldFollowLatest(true, position(1400), position(1400)), true);
});

test('reading history survives content growth, unchanged polls, and viewport resizing', () => {
  assert.equal(shouldFollowLatest(false, position(800), position(800, 2600)), false);
  assert.equal(shouldFollowLatest(false, position(800), position(800)), false);
  assert.equal(shouldFollowLatest(false, position(800), position(800, 2000, 1200)), false);
  assert.equal(shouldFollowLatest(false, position(1400), position(1800, 2400)), false);
});

test('auto-follow resumes only after scrolling back down near the bottom', () => {
  assert.equal(shouldFollowLatest(false, position(800), position(1100)), false);
  assert.equal(shouldFollowLatest(false, position(1100), position(1350)), true);
});

test('expanding activity remains detached beyond the old timer even at the bottom', () => {
  assert.equal(shouldFollowLatest(false, position(1400), position(1400)), false);
  assert.equal(shouldFollowLatest(false, position(1400), position(1400, 2400)), false);
});

test('bottom bounce and sub-pixel jitter do not cause a false detach', () => {
  assert.equal(shouldFollowLatest(true, position(1430), position(1400)), true);
  assert.equal(shouldFollowLatest(true, position(1400), position(1399.5)), true);
});
