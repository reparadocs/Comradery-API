This is the backend repository for Comradery. This is a first pass at making this open source so there will be rough edges. Please email me at rishab at comradery dot io to let me know about any problems you run into, big or small, even if you figure out how to fix them yourself.

The general architecture of Comradery is that this repo (Lionhearted) is the API server and is written in Python/Django. The frontend of Comradery is in another repo (Divinity, https://github.com/reparadocs/Comradery-Frontend) and is written in React. Lastly, there is a chat server repo (Spitfire, https://github.com/reparadocs/Comradery-Chat) written in Node. When messages are sent from the frontend, they are posted directly to the server which then uses a Redis pub/sub server to notify the chat server of new messages. The frontend connects to the chat server via websockets for real-time chat! Everything outside of chat is normal REST stuff like you'd expect.

You will need to first create accounts with AWS (this uses s3 for image hosting), Google (for authentication, possibly optional if you don't want to support login via Google), Algolia (for search), Segment (optionally, for analytics), Postmark (email), and Sendgrid (email). Then go to `lionhearted/local_settings.py` and fill in all the relevant data.

You will need to add email templates to Postmark and Sendgrid, you can find these in the `email_templates` folder. This uses Postmark to send notifications (`comment_notification.html`), password reset (`password_reset.html`), and community invitations (`community_invitation.html`) emails and Sendgrid for daily/weekly digest emails (`community_digest.html`).

You should also replace `SECRET_KEY` in `lionhearted/settings.py`. Running locally should be easy though you will need to run Postgres and Redis locally.

This should be easy to setup on Heroku. The web dyno will spin up automatically and you must allocate a Postgres DB to it. You will also need to add a worker dyno - the command to run the worker instance is `python manage.py rqworker default`. You will also need to set `IN_HEROKU` to 1 in the Heroku Config Vars. You will also need to add a Heroku Redis instance to enable real-time chat and Heroku Scheduler for cronjobs. I also suggest Papertrail for logs. Heroku Scheduler details follow:

`python cron.py --rescore-posts` - hourly

`python cron.py --send-newsletter-digests` - daily

`python notifications.py hourly` - hourly

`python notifications.py daily` - daily
