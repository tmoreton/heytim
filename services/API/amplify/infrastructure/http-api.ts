import { Stack } from 'aws-cdk-lib';
import {
  CfnStage,
  CorsHttpMethod,
  HttpApi,
  HttpMethod,
} from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';
import { LogGroup } from 'aws-cdk-lib/aws-logs';

import apiContract from '../functions/api/api-contract.json';

type HttpApiProps = {
  stack: Stack;
  apiFunction: LambdaFunction;
  plaidWebhookFunction: LambdaFunction;
  apiAccessLogGroup: LogGroup;
  allowedOrigins: string[];
  userPoolId: string;
  userPoolClientId: string;
};

const contractMethods: Record<string, HttpMethod> = {
  GET: HttpMethod.GET,
  POST: HttpMethod.POST,
  PUT: HttpMethod.PUT,
  DELETE: HttpMethod.DELETE,
  PATCH: HttpMethod.PATCH,
};

export function addHttpApi({
  stack,
  apiFunction,
  plaidWebhookFunction,
  apiAccessLogGroup,
  allowedOrigins,
  userPoolId,
  userPoolClientId,
}: HttpApiProps): HttpApi {
  const httpApi = new HttpApi(stack, 'HttpApi', {
    corsPreflight: {
      allowOrigins: allowedOrigins,
      allowHeaders: ['authorization', 'content-type'],
      allowMethods: [
        CorsHttpMethod.GET,
        CorsHttpMethod.POST,
        CorsHttpMethod.PUT,
        CorsHttpMethod.PATCH,
        CorsHttpMethod.DELETE,
        CorsHttpMethod.OPTIONS,
      ],
    },
  });
  const authorizer = new HttpJwtAuthorizer(
    'CognitoAuthorizer',
    `https://cognito-idp.${stack.region}.amazonaws.com/${userPoolId}`,
    { jwtAudience: [userPoolClientId] },
  );
  const integration = new HttpLambdaIntegration('ApiIntegration', apiFunction, {
    scopePermissionToRoute: false,
  });
  const plaidIntegration = new HttpLambdaIntegration('PlaidWebhookIntegration', plaidWebhookFunction, {
    scopePermissionToRoute: false,
  });

  const defaultStage = httpApi.defaultStage?.node.defaultChild as CfnStage | undefined;
  if (!defaultStage) throw new Error('HeyTim HTTP API must have a default stage.');
  defaultStage.accessLogSettings = {
    destinationArn: apiAccessLogGroup.logGroupArn,
    format: JSON.stringify({
      requestId: '$context.requestId',
      requestTime: '$context.requestTime',
      httpMethod: '$context.httpMethod',
      routeKey: '$context.routeKey',
      status: '$context.status',
      responseLatency: '$context.responseLatency',
      integrationError: '$context.integrationErrorMessage',
      sourceIp: '$context.identity.sourceIp',
    }),
  };
  defaultStage.defaultRouteSettings = {
    detailedMetricsEnabled: true,
    throttlingBurstLimit: 100,
    throttlingRateLimit: 50,
  };

  for (const route of apiContract.routes) {
    if (route.access !== 'public' && route.access !== 'authenticated') {
      throw new Error(`Unsupported API contract access: ${route.access}`);
    }
    const method = contractMethods[route.method];
    if (!method) throw new Error(`Unsupported API contract method: ${route.method}`);
    httpApi.addRoutes({
      path: route.path,
      methods: [method],
      integration: route.id === 'plaidWebhook' ? plaidIntegration : integration,
      ...(route.access === 'authenticated' ? { authorizer } : {}),
    });
  }

  return httpApi;
}
