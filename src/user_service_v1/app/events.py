import json
import pika
from shared.config.rabbitmq_config import create_channel
import os
from dotenv import load_dotenv

load_dotenv()
QUEUE_NAME = os.getenv('RABBITMQ_QUEUE_NAME')

def publish_user_update_event(user_id, email, address):
    channel, connection = create_channel(QUEUE_NAME)
    event = {
        'userId': user_id,
        'userEmails': email,
        'deliveryAddress': address
    }
    try:
        channel.basic_publish(
            exchange="user_order",
            routing_key=QUEUE_NAME,
            body=json.dumps(event),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        print(f" V1 Published event: {event}", flush=True)
    finally:
        if connection.is_open:
            connection.close()
