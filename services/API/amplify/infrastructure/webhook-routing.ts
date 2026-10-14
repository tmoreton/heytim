import { AttributeType, ProjectionType, Table } from 'aws-cdk-lib/aws-dynamodb';

/** Sparse outbox: only undelivered webhook events carry these index keys. */
export function addWebhookDispatchIndex(table: Table): void {
  table.addGlobalSecondaryIndex({
    indexName: 'WebhookDispatch',
    partitionKey: { name: 'webhookDispatchPk', type: AttributeType.STRING },
    sortKey: { name: 'webhookDispatchSk', type: AttributeType.STRING },
    projectionType: ProjectionType.INCLUDE,
    nonKeyAttributes: ['userId', 'id', 'status', 'dispatchLeaseExpiresAt'],
  });
}
