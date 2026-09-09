import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import type { ASTNode } from 'react-native-markdown-renderer';

import { fitTableColumns, tableColumnWidths } from './markdown-table-layout';

const ColumnWidths = createContext<number[]>([]);

export function MarkdownTable({ node, children }: { node: ASTNode; children: ReactNode }) {
  const [viewportWidth, setViewportWidth] = useState(0);
  const { fontScale } = useWindowDimensions();
  const baseWidths = useMemo(() => tableColumnWidths(node, fontScale), [node, fontScale]);
  const widths = useMemo(() => fitTableColumns(baseWidths, viewportWidth), [baseWidths, viewportWidth]);
  const tableWidth = widths.reduce((sum, width) => sum + width, 0);
  const overflow = viewportWidth > 0 && tableWidth > viewportWidth + 1;

  return (
    <View style={styles.container}>
      {overflow ? <Text style={styles.hint}>Scroll sideways to see all columns →</Text> : null}
      <ScrollView
        horizontal
        testID="markdown-table-scroll"
        accessibilityLabel="Scrollable table"
        accessibilityHint={overflow ? 'Scroll horizontally to read more columns.' : undefined}
        tabIndex={overflow ? 0 : undefined}
        style={styles.viewport}
        onLayout={(event) => setViewportWidth(event.nativeEvent.layout.width)}
        showsHorizontalScrollIndicator
        directionalLockEnabled
        nestedScrollEnabled
        keyboardShouldPersistTaps="handled">
        <ColumnWidths.Provider value={widths}>
          <View style={{ width: tableWidth }}>{children}</View>
        </ColumnWidths.Provider>
      </ScrollView>
    </View>
  );
}

export function MarkdownTableCell({ node, children }: { node: ASTNode; children: ReactNode }) {
  const widths = useContext(ColumnWidths);
  return (
    <View style={[styles.cell, { width: widths[node.index] ?? 120 }]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { width: '100%', minWidth: 0, marginBottom: 8 },
  viewport: { width: '100%', minWidth: 0, flexGrow: 0 },
  hint: { color: '#557063', fontSize: 12, lineHeight: 18, marginBottom: 5 },
  cell: { flexShrink: 0, padding: 10, borderWidth: StyleSheet.hairlineWidth, borderColor: '#CBC8C0' },
});
