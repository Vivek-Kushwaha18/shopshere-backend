# ShopSphere — Entity Relationship Diagram

This document describes the database entities and relationships in the ShopSphere AI-powered multi-vendor e-commerce platform.

## ER Diagram

```mermaid
erDiagram
    USERS ||--o{ PRODUCTS : sells
    CATEGORIES ||--o{ PRODUCTS : categorizes
    CATEGORIES o|--o{ CATEGORIES : contains

    PRODUCTS ||--o{ PRODUCT_VARIANTS : has
    PRODUCTS ||--o{ PRODUCT_IMAGES : has
    PRODUCT_VARIANTS o|--o{ PRODUCT_IMAGES : has
    PRODUCTS ||--o{ PRODUCT_OPTION_GROUPS : defines
    PRODUCT_OPTION_GROUPS ||--o{ PRODUCT_OPTION_VALUES : contains
    PRODUCT_VARIANTS ||--o{ PRODUCT_VARIANT_VALUES : has
    PRODUCT_OPTION_VALUES ||--o{ PRODUCT_VARIANT_VALUES : selected_in

    USERS ||--o| CARTS : owns
    CARTS ||--o{ CART_ITEMS : contains
    PRODUCTS ||--o{ CART_ITEMS : references
    PRODUCT_VARIANTS o|--o{ CART_ITEMS : selects

    USERS ||--o{ ADDRESSES : has
    USERS ||--o{ ORDERS : places
    ORDERS ||--o{ ORDER_ITEMS : contains
    PRODUCTS ||--o{ ORDER_ITEMS : references
    PRODUCT_VARIANTS o|--o{ ORDER_ITEMS : selects
    USERS ||--o{ ORDER_ITEMS : fulfills

    ORDERS ||--o{ PAYMENTS : has
    USERS ||--o{ PAYMENTS : makes
    ORDERS ||--o{ SHIPMENTS : has
    USERS ||--o{ SHIPMENTS : handles

    USERS ||--o{ REVIEWS : writes
    PRODUCTS ||--o{ REVIEWS : receives
    USERS ||--o{ WISHLISTS : owns
    PRODUCTS ||--o{ WISHLISTS : saved_in

    USERS o|--o{ AI_CONVERSATIONS : starts
    AI_CONVERSATIONS ||--o{ AI_MESSAGES : contains

    USERS {
        int id PK
    }

    PRODUCTS {
        int id PK
        int seller_id FK
        int category_id FK
    }

    CATEGORIES {
        int id PK
        int parent_id FK
    }

    PRODUCT_VARIANTS {
        int id PK
        int product_id FK
    }

    PRODUCT_IMAGES {
        int id PK
        int product_id FK
        int variant_id FK
    }

    PRODUCT_OPTION_GROUPS {
        int id PK
        int product_id FK
    }

    PRODUCT_OPTION_VALUES {
        int id PK
        int option_group_id FK
    }

    PRODUCT_VARIANT_VALUES {
        int id PK
        int variant_id FK
        int option_value_id FK
    }

    CARTS {
        int id PK
        int user_id FK
    }

    CART_ITEMS {
        int id PK
        int cart_id FK
        int product_id FK
        int variant_id FK
    }

    ADDRESSES {
        int id PK
        int user_id FK
    }

    ORDERS {
        int id PK
        int user_id FK
    }

    ORDER_ITEMS {
        int id PK
        int order_id FK
        int product_id FK
        int variant_id FK
        int seller_id FK
    }

    PAYMENTS {
        int id PK
        int order_id FK
        int user_id FK
    }

    SHIPMENTS {
        int id PK
        int order_id FK
        int seller_id FK
    }

    REVIEWS {
        int id PK
        int user_id FK
        int product_id FK
    }

    WISHLISTS {
        int id PK
        int user_id FK
        int product_id FK
    }

    AI_CONVERSATIONS {
        int id PK
        int user_id FK
    }

    AI_MESSAGES {
        int id PK
        int conversation_id FK
    }

    COUPONS {
        int id PK
    }