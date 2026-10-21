# ShopSphere Backend API

**Backend services for ShopSphere — an AI-Powered Multi-Vendor E-Commerce Platform**

ShopSphere Backend is a REST API built with FastAPI and Python. It powers the ShopSphere e-commerce platform, supporting customer authentication, seller product management, shopping carts, orders, payments, reviews, inventory, shipments, and AI-assisted shopping.

The backend uses PostgreSQL for persistent data storage and SQLAlchemy for database access. It integrates with external services such as Stripe and the OpenAI API.

## Features

### Authentication and Authorization
- User registration and login.
- Email verification workflows.
- JWT access and refresh token authentication.
- Role-based access for customers, sellers, and administrators.
- Protected API endpoints.

### Product and Category Management
- Product creation and management.
- Product search and category filtering.
- Product image management.
- Product options and variants.
- Inventory and stock information.
- Seller-specific product management.

### Shopping Cart and Orders
- Shopping cart operations.
- Order creation and order history.
- Order status management.
- Stock and inventory workflows.
- Customer address management.
- Shipment information and tracking.

### Payments
- Stripe payment integration.
- Payment status management.
- Payment-related API endpoints.

### Reviews and Promotions
- Product reviews and ratings.
- Coupon management.
- Customer coupon functionality.
- Reporting and analytics endpoints.

### AI Shopping Assistant
- Integration with the OpenAI API.
- AI-powered shopping assistance.
- Conversation persistence through the backend.

### Infrastructure
- PostgreSQL database.
- Asynchronous database access with SQLAlchemy.
- FastAPI interactive API documentation.
- Docker image builds.
- Configurable local or cloud-based product image storage.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming language |
| FastAPI | REST API framework |
| PostgreSQL | Relational database |
| SQLAlchemy | Database ORM and queries |
| asyncpg | Asynchronous PostgreSQL driver |
| Pydantic | Data validation and schemas |
| JWT | Token-based authentication |
| Stripe | Payment integration |
| OpenAI API | AI shopping assistant |
| Docker | Application containerization |
| Alembic | Database migrations, where configured |

## Project Structure

```text
backend/
├── app/
│   ├── api/
│   │   ├── auth.py
│   │   ├── product.py
│   │   ├── product_variants.py
│   │   ├── product_options.py
│   │   ├── product_variant_images.py
│   │   ├── cart.py
│   │   ├── order.py
│   │   ├── payment.py
│   │   ├── address.py
│   │   ├── wishlist.py
│   │   ├── review.py
│   │   ├── shipment.py
│   │   ├── coupon.py
│   │   ├── customer_coupon.py
│   │   ├── reports.py
│   │   └── chat.py
│   ├── core/
│   ├── database/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   └── utils/
├── docs/
├── uploads/
├── main.py
├── requirements.txt
├── Dockerfile
└── README.md
```

*This is a representative structure; individual files and optional directories may vary.*

## Prerequisites

Install the following:

- Python 3.12 or another version supported by the project dependencies.
- PostgreSQL 16 or a compatible PostgreSQL server.
- pip.
- Git.
- Docker Engine (for containerized execution).

You will also need credentials for the external services you intend to use, such as Stripe and OpenAI.

## Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/Vivek-Kushwaha18/shopshere-backend.git
cd shopshere-backend
```

### 2. Create a virtual environment

On Linux:

```bash
python -m venv venv
source venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the backend root directory.

Example configuration:

```env
DATABASE_URL=postgresql+asyncpg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME

SECRET_KEY=replace_with_a_secure_secret
ALGORITHM=HS256

OPENAI_API_KEY=your_openai_api_key

STRIPE_SECRET_KEY=your_stripe_secret_key
STRIPE_PUBLISHABLE_KEY=your_stripe_publishable_key
```

Use the actual environment variable names required by your application. Configure email, token expiry, image storage, and other settings as needed.

**Database configuration notes:**

- `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_NAME` must match your PostgreSQL setup.
- For your existing local database, verify the database name before configuring the URL.
- If PostgreSQL runs in Docker, the database hostname depends on whether the backend runs on your host or inside a Docker network.
- `host.docker.internal` is not automatically resolvable in every Linux environment.

Never commit `.env` files or expose API keys, database passwords, or authentication secrets.

### 4. Start the development server

From the backend directory, with the virtual environment activated:

```bash
uvicorn main:app --reload
```

The API will be available at:

- Base URL: `http://127.0.0.1:8000`
- Swagger documentation: `http://127.0.0.1:8000/docs`
- ReDoc documentation: `http://127.0.0.1:8000/redoc`
- Health endpoint: `http://127.0.0.1:8000/health`

The database and required external services must be configured and reachable for their dependent endpoints to work.

## API Overview

The backend provides API groups for the following functionality:

| API area | Purpose |
|---|---|
| Authentication | Registration, login, and verification |
| Products | Product discovery and management |
| Categories | Category listing and filtering |
| Cart | Shopping cart operations |
| Orders | Order creation and management |
| Payments | Payment processing and status |
| Addresses | Customer address management |
| Wishlist | Saved products |
| Reviews | Product ratings and feedback |
| Product variants | Product variant management |
| Product options | Configurable product options |
| Shipments | Shipment and delivery information |
| Coupons | Promotions and discounts |
| Reports | Administrative reporting |
| AI conversations | Shopping assistant conversations |

For the exact route paths, request methods, parameters, and response schemas, use the generated API documentation at `/docs`. Individual route prefixes may differ by router.

## Database

ShopSphere uses PostgreSQL with SQLAlchemy asynchronous database access.

The backend connection URL uses the `postgresql+asyncpg` driver.

Before using the API, make sure that:

1. PostgreSQL is running.
2. The configured database exists.
3. The configured user has the required privileges.
4. `DATABASE_URL` points to a hostname reachable from the backend process.
5. The required database tables and migrations have been initialized.

If Alembic is configured for your current project state, use its migration workflow to apply schema changes. Avoid deleting production or development database volumes to resolve ordinary connection problems.

## Docker

Docker lets you package the backend and run it in a container.

### 1. Build the backend image

Run this command from the directory containing the backend `Dockerfile`:

```bash
cd ~/projects/shopshere/backend
sudo docker build -t shopsphere-backend .
```

### 2. Check the image

```bash
sudo docker images shopsphere-backend
```

### 3. Run the backend container

The following is a template. It assumes that your `.env` file contains the correct settings and that the database hostname is reachable from the container.

```bash
sudo docker run -d \
  --name shopsphere-backend \
  --env-file .env \
  -p 8000:8000 \
  shopsphere-backend
```

This command requires the image's configured startup command to run the API on `0.0.0.0:8000`. Verify that your Dockerfile uses the correct startup command and port.

**Important:** If PostgreSQL is another Docker container, the backend must be connected to a compatible Docker network, and `DATABASE_URL` must use a hostname resolvable on that network. Publishing a port, configuring a Docker network, and setting the database URL are separate tasks.

### 4. View container status

```bash
sudo docker ps -a
```

### 5. View backend logs

```bash
sudo docker logs --tail=100 shopsphere-backend
```

Follow the logs continuously:

```bash
sudo docker logs -f shopsphere-backend
```

### 6. Rebuild after code changes

When your source code is copied into the image rather than mounted as a volume, rebuild the image after changing the backend:

```bash
cd ~/projects/shopshere/backend
sudo docker build -t shopsphere-backend .
```

Rebuilding the image does not update an already-running container. Recreate the backend container using its required environment variables, network, ports, and mounts to run the new image.

Do not remove database containers or volumes just to update backend code.

## Security Best Practices

- Store secrets in environment variables.
- Keep `.env` files out of version control.
- Use strong, randomly generated authentication secrets.
- Validate and authorize protected operations on the backend.
- Restrict seller operations to products and resources they are permitted to manage.
- Validate payment status on the server rather than trusting frontend state.
- Configure CORS for trusted frontend origins.
- Use HTTPS and appropriate production settings when deploying.
- Avoid logging passwords, tokens, and payment secrets.

## Development Workflow

1. Create a feature branch before substantial changes.
2. Implement the API changes in the appropriate module.
3. Validate request and response schemas.
4. Test database operations and authorization.
5. Check the endpoints in `/docs`.
6. Rebuild the Docker image when required.
7. Review logs and verify the affected workflows.

## Future Improvements

Potential enhancements include:

- Automated unit and integration tests.
- Continuous integration and deployment.
- API rate limiting and stronger abuse protection.
- Structured logging and monitoring.
- More comprehensive API and deployment documentation.

## Author

**Vivek Kushwaha**

GitHub: [Vivek-Kushwaha18](https://github.com/Vivek-Kushwaha18)

## License

Add a `LICENSE` file to specify the terms under which this project may be used, modified, and distributed. Until a license is added, no open-source reuse permissions should be assumed.
