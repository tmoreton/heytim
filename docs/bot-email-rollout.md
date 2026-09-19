# Bot email rollout

The first release gives each bot a receive-only address at `bots.heytim.ai`. An owner turns on the address in Bot Inbox, reviews incoming text there, and chooses **Discuss with bot** to place the text in the chat composer. Incoming mail never starts an agent run by itself. Attachments are named in the inbox but are not downloadable or sent to the bot in this release.

## Delivery path

Amazon SES receives mail for the subdomain in `us-east-1`, checks spam and viruses, and writes the raw MIME message to a private S3 bucket. An SNS notification invokes the email receiver, which uses the SES envelope recipient to identify the owner and bot. The receiver extracts a bounded plain-text preview and saves it in the existing DynamoDB user partition. Failed SNS deliveries and receiver invocations go to a queue for inspection, and duplicate SES deliveries have the same inbox key. Raw S3 objects have a seven-day lifecycle; inbox previews stay until the owner deletes them, deletes the bot, or deletes the account.

The address contains an opaque owner identifier, bot identifier digest, and a random route token. Bot renames do not change the address. Turning off the inbox removes the route token; replacing the address generates a new one. Old addresses are never assigned to another bot. Mail that fails SES spam or virus checks is not added to an inbox. The UI marks mail without a passing DMARC verdict as unverified. The email body is external content, and the owner must review it before asking a bot to use it.

## Activation steps

1. The AWS account `188757775631` currently has one active SES receipt rule set in `us-east-1`: `inboxai-inboxai-cc`. Its enabled `inboxai-inbound` rule receives `inboxai.cc` mail for another application. Keep this set active and set `HEYTIM_SES_RULE_SET_NAME=inboxai-inboxai-cc` so the bot rule joins it. Recheck this state before the receive-stage deployment.
2. Deploy the production backend with `HEYTIM_BOT_EMAIL_STAGE=identity` and `HEYTIM_BOT_EMAIL_AVAILABLE=false`. The production release workflow is set to these values. This creates only the SES identity and DNS outputs. Review the CloudFormation change set before deploying. If the identity already exists outside this stack, resolve ownership or import it before this step.
3. At the domain registrar, publish the three CNAME name/value pairs from the stack outputs for `bots.heytim.ai` and wait for SES identity verification. Leave the MX record until the receiver is deployed. The root `heytim.ai` MX records remain separate.
4. Change the production release workflow to `HEYTIM_BOT_EMAIL_STAGE=receive` while keeping `HEYTIM_SES_RULE_SET_NAME=inboxai-inboxai-cc` and `HEYTIM_BOT_EMAIL_AVAILABLE=false`, then deploy again. This adds the bot receipt rule to the already-active set, plus private storage, topic, failure queue, and receiver. Keep `HEYTIM_BOT_EMAIL_STAGE=receive` in subsequent deployments so these resources remain managed by the stack.
5. Add an MX record for `bots.heytim.ai` with priority `10` and value `inbound-smtp.us-east-1.amazonaws.com`, and confirm DNS propagation. Change `HEYTIM_BOT_EMAIL_AVAILABLE=true` in the production release workflow and redeploy the API. The app can then turn on a bot address.
6. Send a test email to an enabled bot address and confirm that it appears once in Bot Inbox. Check a second bot, a disabled or replaced address, a message with an attachment, and a failed-DMARC sender before releasing the app update.

AWS inspection on September 18, 2026 confirmed that `bots.heytim.ai` has no SES identity and no MX record. The domain uses `dns1.registrar-servers.com` and `dns2.registrar-servers.com`; there is no matching Route 53 hosted zone in this AWS account. Publish the DNS records through the domain registrar.
Production deployments require an explicit `HEYTIM_BOT_EMAIL_STAGE` value. Omitting it stops synthesis rather than silently changing the mail resources.

## References

- [SES receiving setup](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-setting-up.html)
- [SES receipt rule sets](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-receipt-rules-console-walkthrough.html)
- [SES envelope recipients and notification fields](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-notifications-contents.html)
