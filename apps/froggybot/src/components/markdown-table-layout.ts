import type { ASTNode } from 'react-native-markdown-renderer';

const cellText = (node: ASTNode): string => node.children.length
  ? node.children.map(cellText).join('')
  : node.content;

export function tableColumnWidths(table: ASTNode, fontScale = 1): number[] {
  const widths: number[] = [];
  const visit = (node: ASTNode) => {
    if (node.type === 'tr') {
      node.children.forEach((cell, column) => {
        const length = Array.from(cellText(cell).trim()).length;
        // Short identifiers stay compact; prose gets room without creating giant columns.
        const width = length <= 3 ? 56 : Math.min(300, Math.max(120, length * 8 + 24));
        widths[column] = Math.max(widths[column] ?? 0, Math.ceil(width * Math.max(1, fontScale)));
      });
    } else {
      node.children.forEach(visit);
    }
  };
  visit(table);
  return widths;
}

export function fitTableColumns(widths: number[], availableWidth: number): number[] {
  const total = widths.reduce((sum, width) => sum + width, 0);
  if (!total || availableWidth <= total) return widths;
  // Grow to fill a desktop bubble, but never squeeze columns to fit a phone.
  return widths.map((width) => width * availableWidth / total);
}
