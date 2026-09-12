import { useEffect, useState } from 'react';
import { StyleSheet, Text } from 'react-native';

import type { Message } from '@froggybot/contracts';
import { isActiveResponse, messageTimingLabel } from '@froggybot/client';

type Props = {
  message: Message;
  assistant: boolean;
};

export function MessageTimingLabel({ message, assistant }: Props) {
  const active = isActiveResponse(message);
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (!active) return undefined;
    const refresh = () => setNow(Date.now());
    const initial = setTimeout(refresh, 0);
    const timer = setInterval(refresh, 1000);
    return () => {
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, [active]);

  const label = messageTimingLabel(message, now);
  if (!label) return null;
  return (
    <Text
      accessibilityLabel={label}
      style={[styles.timing, assistant ? styles.assistantTiming : styles.userTiming]}>
      {label}
    </Text>
  );
}

const styles = StyleSheet.create({
  timing: { color: '#817D75', fontSize: 9, marginHorizontal: 6, marginTop: 4 },
  assistantTiming: { alignSelf: 'flex-start' },
  userTiming: { alignSelf: 'flex-end' },
});
