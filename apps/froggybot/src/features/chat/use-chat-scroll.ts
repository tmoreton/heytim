import { useCallback, useEffect, useRef, useState } from 'react';
import type { FlatList, LayoutChangeEvent, NativeScrollEvent, NativeSyntheticEvent } from 'react-native';

import type { Message } from '@/lib/types';

import { shouldFollowLatest, type ScrollPosition } from './chat-scroll-policy';

export function useChatScroll() {
  const list = useRef<FlatList<Message>>(null);
  const following = useRef(true);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const pendingFrame = useRef<number | undefined>(undefined);
  const position = useRef<ScrollPosition>({ offset: 0, contentHeight: 0, viewportHeight: 0 });
  const layout = useRef({ contentHeight: 0, viewportHeight: 0 });

  const cancelPendingScroll = useCallback(() => {
    if (pendingFrame.current !== undefined) cancelAnimationFrame(pendingFrame.current);
    pendingFrame.current = undefined;
  }, []);

  const setFollowing = useCallback((value: boolean) => {
    if (following.current === value) return;
    following.current = value;
    setShowJumpToLatest(!value);
    if (!value) cancelPendingScroll();
  }, [cancelPendingScroll]);

  const scrollToLatest = useCallback(() => {
    if (!following.current) return;
    cancelPendingScroll();
    pendingFrame.current = requestAnimationFrame(() => {
      pendingFrame.current = undefined;
      if (!following.current || !layout.current.viewportHeight) return;
      const offset = Math.max(0, layout.current.contentHeight - layout.current.viewportHeight);
      position.current = { ...layout.current, offset };
      // Use measured content, including padding, rather than FlatList's estimated
      // final item offset (which can stop short after variable-height replies).
      list.current?.scrollToOffset({ offset, animated: false });
    });
  }, [cancelPendingScroll]);

  const onContentSizeChange = useCallback((_width: number, height: number) => {
    layout.current.contentHeight = height;
    scrollToLatest();
  }, [scrollToLatest]);

  const onLayout = useCallback((event: LayoutChangeEvent) => {
    layout.current.viewportHeight = event.nativeEvent.layout.height;
    scrollToLatest();
  }, [scrollToLatest]);

  const onScroll = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    const next = {
      offset: Math.max(0, contentOffset.y),
      contentHeight: contentSize.height,
      viewportHeight: layoutMeasurement.height,
    };
    setFollowing(shouldFollowLatest(following.current, position.current, next));
    position.current = next;
  }, [setFollowing]);

  const preserveScrollPosition = useCallback(() => setFollowing(false), [setFollowing]);
  const jumpToLatest = useCallback(() => {
    setFollowing(true);
    scrollToLatest();
  }, [setFollowing, scrollToLatest]);

  useEffect(() => cancelPendingScroll, [cancelPendingScroll]);

  return { list, onScroll, onLayout, onContentSizeChange, preserveScrollPosition, jumpToLatest, showJumpToLatest };
}
