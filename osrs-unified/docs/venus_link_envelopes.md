# Venus Docs Page - Link Bus Envelopes

This page explains the flow of messages through the Venus link bus envelopes. It’s a simplified overview for understanding how Venus communicates.

## Envelope Structure

Each envelope contains:

*   **Message ID:** A unique identifier for the message.
*   **Sender:** The component sending the message.
*   **Recipient:** The component receiving the message.
*   **Payload:** The actual data being transmitted.

## Flow

1.  A component creates a message.
2.  The message is packaged into an envelope.
3.  The envelope is sent via the link bus.
4.  The recipient component receives and processes the envelope.
