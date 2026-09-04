import Markdown from 'react-native-markdown-renderer';
import { Platform, StyleSheet } from 'react-native';

type Props = {
  children: string;
};

const monospace = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });

export function MessageMarkdown({ children }: Props) {
  return (
    <Markdown allowedImageHandlers={[]} defaultImageHandler={null} style={markdownStyles}>
      {children}
    </Markdown>
  );
}

const markdownStyles = StyleSheet.create({
  text: { color: '#24231F', fontSize: 15, lineHeight: 21 },
  paragraph: { marginTop: 0, marginBottom: 8, flexDirection: 'row', flexWrap: 'wrap' },
  headingContainer: { marginTop: 8, marginBottom: 6 },
  heading1Container: { paddingBottom: 5, borderBottomWidth: 0 },
  heading2Container: { paddingBottom: 4, borderBottomWidth: 0 },
  heading1: { color: '#1E1D1A', fontSize: 21, lineHeight: 27, fontWeight: '800' },
  heading2: { color: '#1E1D1A', fontSize: 19, lineHeight: 25, fontWeight: '800' },
  heading3: { color: '#1E1D1A', fontSize: 17, lineHeight: 23, fontWeight: '700' },
  heading4: { color: '#1E1D1A', fontSize: 15, lineHeight: 21, fontWeight: '700' },
  strong: { fontWeight: '800' },
  em: { fontStyle: 'italic' },
  link: { color: '#007A3D', textDecorationLine: 'underline' },
  list: { marginBottom: 8 },
  listUnorderedItem: { flexDirection: 'row', alignItems: 'flex-start', marginTop: 2 },
  listUnorderedItemIcon: { color: '#007A3D', marginLeft: 3, marginRight: 8, fontSize: 17, lineHeight: 21 },
  listUnorderedItemText: { color: '#24231F', fontSize: 15, lineHeight: 21 },
  listOrderedItem: { flexDirection: 'row', alignItems: 'flex-start', marginTop: 2 },
  listOrderedItemIcon: { color: '#656159', minWidth: 20, marginRight: 5, fontSize: 15, lineHeight: 21 },
  listOrderedItemText: { color: '#24231F', fontSize: 15, lineHeight: 21 },
  blockquote: { borderLeftWidth: 3, borderLeftColor: '#8AB69E', paddingLeft: 10, marginBottom: 8 },
  codeInline: {
    color: '#17472F',
    backgroundColor: '#DFE9E2',
    borderRadius: 4,
    fontFamily: monospace,
    fontSize: 13,
    paddingHorizontal: 4,
    paddingVertical: 1,
  },
  codeBlock: {
    color: '#EAF5EE',
    backgroundColor: '#183C2A',
    borderRadius: 9,
    fontFamily: monospace,
    fontSize: 12,
    lineHeight: 18,
    padding: 10,
    marginBottom: 8,
  },
  table: { borderWidth: StyleSheet.hairlineWidth, borderColor: '#CBC8C0', marginBottom: 8 },
  tableHeader: { backgroundColor: '#E2E5DF' },
  tableHeaderCell: { flex: 1, padding: 6, borderWidth: StyleSheet.hairlineWidth, borderColor: '#CBC8C0', fontWeight: '700' },
  tableRowCell: { flex: 1, padding: 6, borderWidth: StyleSheet.hairlineWidth, borderColor: '#CBC8C0' },
});
