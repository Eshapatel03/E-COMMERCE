import { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const getErrorMessage = (detail, fallback) => {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg).filter(Boolean).join(", ") || fallback;
  }
  return fallback;
};

function AuthPage({ mode, onModeChange, onLogin, onSignup, message }) {
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
  });

  const updateField = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
  };

  const submit = (event) => {
    event.preventDefault();
    mode === "login" ? onLogin(form) : onSignup(form);
  };

  return (
    <main className="auth-page">
      <div className="auth-card">
        <p className="section-label">{mode === "login" ? "WELCOME BACK" : "JOIN LUMORA"}</p>
        <h1>{mode === "login" ? "Sign in" : "Create your account"}</h1>
        <p className="auth-intro">
          {mode === "login"
            ? "Sign in to continue shopping."
            : "Create an account to save your place in the collection."}
        </p>
        <form className="auth-form" onSubmit={submit}>
          {mode === "signup" && (
            <label>
              Name
              <input name="name" value={form.name} onChange={updateField} required />
            </label>
          )}
          <label>
            Email
            <input name="email" type="email" value={form.email} onChange={updateField} required />
          </label>
          <label>
            Password
            <input name="password" type="password" value={form.password} onChange={updateField} required />
          </label>
          {mode === "signup" && (
            <label>
              Confirm Password
              <input
                name="confirmPassword"
                type="password"
                value={form.confirmPassword}
                onChange={updateField}
                required
              />
            </label>
          )}
          {mode === "signup" && (
            <p className="password-hint">
              Use 8+ characters with uppercase, lowercase, a number, and a special character.
            </p>
          )}
          <button className="auth-submit-button">
            {mode === "login" ? "Login" : "Sign Up"}
          </button>
          {message && <p className="auth-message">{message}</p>}
        </form>
        <button className="auth-switch" onClick={() => onModeChange(mode === "login" ? "signup" : "login")}>
          {mode === "login" ? "Need an account? Sign up" : "Already have an account? Login"}
        </button>
      </div>
    </main>
  );
}

function ProductCard({ product, getImageUrl, onSelect, onAddToCart }) {
  return (
    <div className="product-card">
      <div
        className="product-image"
        onClick={() => onSelect(product)}
        role="button"
        tabIndex="0"
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") onSelect(product);
        }}
      >
        <img src={getImageUrl(product.image)} alt={product.name} />
      </div>
      <div className="product-info">
        <p className="product-category">{product.category}</p>
        <h3>{product.name}</h3>
        <div className="product-bottom">
          <span className="price">${product.price}</span>
          <button onClick={() => onAddToCart(product)}>Add to Cart</button>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [products, setProducts] = useState([]);
  const [productPage, setProductPage] = useState(1);
  const [productPageCount, setProductPageCount] = useState(1);
  const [productTotal, setProductTotal] = useState(0);
  const [availableCategories, setAvailableCategories] = useState([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [cart, setCart] = useState([]);
  const [isCartOpen, setIsCartOpen] = useState(
    () => window.location.hash === "#cart"
  );
  const [isAdminOpen, setIsAdminOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isProfilePageOpen, setIsProfilePageOpen] = useState(false);
  const [adminForm, setAdminForm] = useState({
    name: "",
    category: "",
    price: "",
    stock: "",
    image: null,
  });
  const [adminMessage, setAdminMessage] = useState(null);
  const [adminProducts, setAdminProducts] = useState([]);
  const [editingProductId, setEditingProductId] = useState(null);
  const [adminFormKey, setAdminFormKey] = useState(0);
  const [isSubmittingProduct, setIsSubmittingProduct] = useState(false);
  const [cartMessage, setCartMessage] = useState("");
  const [authUser, setAuthUser] = useState(() => {
    const savedUser = localStorage.getItem("lumora_user");
    return savedUser ? JSON.parse(savedUser) : null;
  });
  const [authMode, setAuthMode] = useState("login");
  const [authMessage, setAuthMessage] = useState("");
  const authHeaders = () => {
    const token = localStorage.getItem("lumora_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  };

  const openCart = () => {
    if (window.location.hash !== "#cart") {
      window.history.pushState(
        { ...window.history.state, cartRoute: true },
        "",
        `${window.location.pathname}${window.location.search}#cart`
      );
    }
    setIsCartOpen(true);
    setIsAdminOpen(false);
    setIsProfilePageOpen(false);
  };

  const closeCart = () => {
    if (window.location.hash === "#cart") {
      if (window.history.state?.cartRoute) {
        window.history.back();
        return;
      }

      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${window.location.search}#shop`
      );
    }
    setIsCartOpen(false);
  };

  useEffect(() => {
    const syncCartWithUrl = () => {
      const cartIsOpen = window.location.hash === "#cart";
      setIsCartOpen(cartIsOpen);
      if (cartIsOpen) {
        setIsAdminOpen(false);
        setIsProfilePageOpen(false);
      }
    };

    window.addEventListener("hashchange", syncCartWithUrl);
    window.addEventListener("popstate", syncCartWithUrl);
    syncCartWithUrl();
    return () => {
      window.removeEventListener("hashchange", syncCartWithUrl);
      window.removeEventListener("popstate", syncCartWithUrl);
    };
  }, []);

  const loadProducts = useCallback((page) => {
    const params = new URLSearchParams({
      page,
      page_size: 8,
      ...(search ? { keyword: search } : {}),
      ...(category !== "All" ? { category } : {}),
    });
    fetch(`${API_BASE_URL}/products?${params}`)
      .then((response) => response.json())
      .then((data) => {
        setProducts(data.products || data);
        setProductPageCount(data.total_pages || 1);
        setProductTotal(data.total || (data.products || data).length);
        setAvailableCategories(data.categories || []);
      })
      .catch((error) => console.error("Error:", error));
  }, [category, search]);

  useEffect(() => {
    loadProducts(productPage);
  }, [loadProducts, productPage]);

  useEffect(() => {
    if (isAdminOpen) {
      fetch(`${API_BASE_URL}/products?page_size=100`, { headers: authHeaders() })
        .then((response) => response.json())
        .then((data) => setAdminProducts(data.products || data))
        .catch((error) => console.error("Error:", error));
    }
  }, [isAdminOpen]);

  const handleLogin = async (form) => {
    setAuthMessage("");
    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(getErrorMessage(data.detail, "Unable to log in"));
      }
      localStorage.setItem("lumora_token", data.token);
      localStorage.setItem("lumora_user", JSON.stringify(data.user));
      setAuthUser(data.user);
      setIsAdminOpen(data.user.role === "admin");
      setIsCartOpen(window.location.hash === "#cart");
      setIsProfileOpen(false);
      setIsProfilePageOpen(false);
      setAuthMode("login");
      setAuthMessage("");
    } catch (error) {
      setAuthMessage(error.message);
    }
  };

  const handleSignup = async (form) => {
    setAuthMessage("");
    try {
      const response = await fetch(`${API_BASE_URL}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          email: form.email,
          password: form.password,
          confirm_password: form.confirmPassword,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(getErrorMessage(data.detail, "Unable to sign up"));
      }
      setAuthMode("login");
      setAuthMessage("Account created successfully. Please log in.");
    } catch (error) {
      setAuthMessage(error.message);
    }
  };

  const handleLogout = async () => {
    try {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST",
        headers: authHeaders(),
      });
    } finally {
      localStorage.removeItem("lumora_token");
      localStorage.removeItem("lumora_user");
      setAuthUser(null);
      setIsAdminOpen(false);
      closeCart();
      setIsProfileOpen(false);
      setIsProfilePageOpen(false);
      setAuthMode("login");
    }
  };

  const getImageUrl = (image) =>
    image.startsWith("data/images/")
      ? `${API_BASE_URL}/images/${image.split("/").pop()}`
      : image;

  const categories = useMemo(() => ["All", ...availableCategories], [
    availableCategories,
  ]);

  const categoryCards = useMemo(
    () => availableCategories.map((item) => ({
      name: item,
      product: products.find((product) => product.category === item),
    })),
    [availableCategories, products]
  );

  const filteredProducts = products;

  const selectCategory = (item) => {
    setProductPage(1);
    setCategory(item);
    document.getElementById("shop")?.scrollIntoView({ behavior: "smooth" });
  };

  const addToCart = (product) => {
    const existingProduct = cart.find((item) => item.id === product.id);

    if (existingProduct && existingProduct.quantity >= product.stock) {
      return;
    }

    setCart((currentCart) => {
      const currentProduct = currentCart.find(
        (item) => item.id === product.id
      );

      if (currentProduct) {
        return currentCart.map((item) =>
          item.id === product.id
            ? { ...item, quantity: item.quantity + 1 }
            : item
        );
      }

      return [...currentCart, { ...product, quantity: 1 }];
    });
    setCartMessage(`${product.name} added to cart`);
    window.setTimeout(() => setCartMessage(""), 2200);
  };

  const increaseQuantity = (productId) => {
    setCart((currentCart) =>
      currentCart.map((item) => {
        if (item.id !== productId) {
          return item;
        }

        if (item.quantity >= item.stock) {
          return item;
        }

        return {
          ...item,
          quantity: item.quantity + 1,
        };
      })
    );
  };

  const decreaseQuantity = (productId) => {
    setCart((currentCart) =>
      currentCart
        .map((item) => {
          if (item.id !== productId) {
            return item;
          }

          return {
            ...item,
            quantity: item.quantity - 1,
          };
        })
        .filter((item) => item.quantity > 0)
    );
  };

  const removeFromCart = (productId) => {
    setCart((currentCart) =>
      currentCart.filter((item) => item.id !== productId)
    );
  };

  const cartCount = cart.reduce(
    (total, item) => total + item.quantity,
    0
  );

  const cartTotal = cart.reduce(
    (total, item) => total + item.price * item.quantity,
    0
  );

  const updateAdminForm = (event) => {
    const { name, value, files } = event.target;
    setAdminForm((currentForm) => ({
      ...currentForm,
      [name]: files ? files[0] : value,
    }));
  };

  const resetAdminForm = () => {
    setAdminForm({
      name: "",
      category: "",
      price: "",
      stock: "",
      image: null,
    });
    setEditingProductId(null);
    setAdminMessage(null);
    setAdminFormKey((key) => key + 1);
  };

  const submitProduct = async (event) => {
    event.preventDefault();
    setAdminMessage(null);

    if (!editingProductId && !adminForm.image) {
      setAdminMessage({ type: "error", text: "Please select a product image." });
      return;
    }

    const formData = new FormData();
    formData.append("name", adminForm.name);
    formData.append("category", adminForm.category);
    formData.append("price", adminForm.price);
    formData.append("stock", adminForm.stock);
    if (adminForm.image) {
      formData.append("image", adminForm.image);
    }

    setIsSubmittingProduct(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}/products${editingProductId ? `/${editingProductId}` : ""}`,
        {
        method: editingProductId ? "PUT" : "POST",
        body: formData,
        headers: authHeaders(),
        }
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to add product.");
      }

      const successMessage = `${data.name} was ${editingProductId ? "updated" : "added"} successfully.`;
      resetAdminForm();
      setAdminMessage({ type: "success", text: successMessage });
      event.target.reset();
      loadProducts(productPage);
      const adminResponse = await fetch(`${API_BASE_URL}/products?page_size=100`, {
        headers: authHeaders(),
      });
      const adminData = await adminResponse.json();
      setAdminProducts(adminData.products || adminData);
    } catch (error) {
      setAdminMessage({ type: "error", text: error.message });
    } finally {
      setIsSubmittingProduct(false);
    }
  };

  const startEditingProduct = (product) => {
    setEditingProductId(product.id);
    setAdminForm({
      name: product.name,
      category: product.category,
      price: product.price,
      stock: product.stock,
      image: null,
    });
    setAdminMessage(null);
  };

  const deleteProduct = async (product) => {
    if (!window.confirm(`Delete ${product.name}?`)) return;
    try {
      const response = await fetch(`${API_BASE_URL}/products/${product.id}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to delete product.");
      setAdminMessage({ type: "success", text: `${product.name} was deleted.` });
      setAdminProducts((current) => current.filter((item) => item.id !== product.id));
      loadProducts(productPage);
    } catch (error) {
      setAdminMessage({ type: "error", text: error.message });
    }
  };

  return (
    <div className="app">
      <nav className={`navbar ${!authUser ? "auth-navbar" : ""}`}>
        <div className="logo">LUMORA</div>

        {!authUser ? (
          <div className="nav-links">
            <button className="nav-admin-link" onClick={() => { setAuthMode("login"); setAuthMessage(""); }}>Login</button>
            <button className="nav-admin-link" onClick={() => { setAuthMode("signup"); setAuthMessage(""); }}>Sign Up</button>
          </div>
        ) : (
          <div className="nav-links">
            <a href="#shop" onClick={() => { setIsCartOpen(false); setIsAdminOpen(false); setIsProfilePageOpen(false); }}>Shop</a>
            <a href="#features" onClick={() => { setIsCartOpen(false); setIsAdminOpen(false); setIsProfilePageOpen(false); }}>Why Us</a>
            <a href="#contact">Contact</a>
            {authUser.role === "admin" && (
              <button className="nav-admin-link" onClick={() => {
                setIsAdminOpen(true);
                closeCart();
                setIsProfilePageOpen(false);
              }}>
                Admin / Dashboard
              </button>
            )}
            <div className="profile-menu">
              <button
                className="profile-menu-button"
                onClick={() => setIsProfileOpen((isOpen) => !isOpen)}
                aria-expanded={isProfileOpen}
              >
                <span aria-hidden="true">👤</span> {authUser.role === "admin" ? "Admin" : authUser.name}
              </button>
              {isProfileOpen && (
                <div className="profile-dropdown">
                  <button onClick={() => {
                    setIsProfilePageOpen(true);
                    setIsProfileOpen(false);
                    setIsAdminOpen(false);
                    closeCart();
                  }}>
                    Profile
                  </button>
                  {authUser.role === "admin" && (
                    <button onClick={() => {
                      setIsAdminOpen(true);
                      setIsProfileOpen(false);
                      setIsProfilePageOpen(false);
                      closeCart();
                    }}>
                      Admin Dashboard
                    </button>
                  )}
                  <button onClick={handleLogout}>Logout</button>
                </div>
              )}
            </div>
          </div>
        )}

        {authUser && (
          <button
            className="cart-summary"
            onClick={openCart}
            aria-label={`${cartCount} items in cart`}
          >
            <span>Cart</span>
            <span className="cart-count">{cartCount}</span>
          </button>
        )}
      </nav>

      {!authUser ? (
        <AuthPage
          mode={authMode}
          onModeChange={(mode) => { setAuthMode(mode); setAuthMessage(""); }}
          onLogin={handleLogin}
          onSignup={handleSignup}
          message={authMessage}
        />
      ) : isProfilePageOpen ? (
        <section className="profile-page">
          <div className="profile-page-card">
            <p className="section-label">YOUR ACCOUNT</p>
            <h1>Profile</h1>
            <div className="profile-details">
              <div>
                <span>Name</span>
                <strong>{authUser.name}</strong>
              </div>
              <div>
                <span>Email</span>
                <strong>{authUser.email}</strong>
              </div>
              <div>
                <span>Role</span>
                <strong>{authUser.role === "admin" ? "Admin" : "User"}</strong>
              </div>
            </div>
            <button
              className="continue-shopping-button"
              onClick={() => setIsProfilePageOpen(false)}
            >
              Back to Shop
            </button>
          </div>
        </section>
      ) : isAdminOpen ? (
        <section className="admin-page">
          <div className="admin-page-header">
            <div>
              <p className="section-label">PRODUCT MANAGEMENT</p>
              <h1>{editingProductId ? "Edit Product" : "Add Product"}</h1>
            </div>
            <button
              className="continue-shopping-button"
              onClick={() => {
                setIsAdminOpen(false);
                resetAdminForm();
              }}
            >
              Back to Shop
            </button>
          </div>

          <div className="admin-content">
            <form className="admin-form" key={adminFormKey} onSubmit={submitProduct}>
              <div className="admin-form-header">
                <p className="section-label">PRODUCT DETAILS</p>
                <h2>{editingProductId ? "Edit Product" : "Add New Product"}</h2>
                <p>
                  {editingProductId
                    ? "Update the product information below"
                    : "Add product details to your store"}
                </p>
              </div>

              <div className="admin-form-fields">
                <label>
                  Product Name
                  <input
                    name="name"
                    value={adminForm.name}
                    onChange={updateAdminForm}
                    required
                  />
                </label>
                <label>
                  Category
                  <input
                    name="category"
                    value={adminForm.category}
                    onChange={updateAdminForm}
                    required
                  />
                </label>
                <label>
                  Price
                  <input
                    name="price"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={adminForm.price}
                    onChange={updateAdminForm}
                    required
                  />
                </label>
                <label>
                  Stock
                  <input
                    name="stock"
                    type="number"
                    min="0"
                    step="1"
                    value={adminForm.stock}
                    onChange={updateAdminForm}
                    required
                  />
                </label>
              </div>

              <div className="admin-image-section">
                <div>
                  <h3>Product Image</h3>
                  <p>Upload a clear image for your store listing.</p>
                </div>
                <input
                  name="image"
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/gif"
                  onChange={updateAdminForm}
                  required={!editingProductId}
                />
              </div>

              <div className="admin-form-actions">
                <button
                  className="admin-cancel-button"
                  type="button"
                  onClick={resetAdminForm}
                >
                  Cancel
                </button>
                <button
                  className="admin-submit-button"
                  disabled={isSubmittingProduct}
                >
                  {isSubmittingProduct
                    ? editingProductId ? "Saving Product..." : "Adding Product..."
                    : editingProductId ? "Update Product" : "Add Product"}
                </button>
              </div>
            </form>
            {adminMessage && (
              <p className={`admin-message ${adminMessage.type}`} role="status">
                {adminMessage.text}
              </p>
            )}
            <div className="admin-list">
              <h2>Products</h2>
              {adminProducts.map((product) => (
                <div className="admin-list-item" key={product.id}>
                  <span>
                    {product.name} <small>({product.category})</small>
                  </span>
                  <span>${product.price} · {product.stock} in stock</span>
                  <span className="admin-list-actions">
                    <button onClick={() => startEditingProduct(product)}>Edit</button>
                    <button onClick={() => deleteProduct(product)}>Delete</button>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : isCartOpen ? (
        <section className="cart-page">
          <div className="cart-page-header">
            <div>
              <p className="section-label">YOUR SELECTION</p>
              <h1>Your Cart</h1>
            </div>
            <button
              className="continue-shopping-button"
              onClick={closeCart}
            >
              Continue Shopping
            </button>
          </div>

          {cart.length > 0 ? (
            <div className="cart-page-content">
              <div className="cart-page-items">
                {cart.map((item) => (
                  <div className="cart-page-item" key={item.id}>
                    <div>
                      <strong>{item.name}</strong>
                      <p>
                        ${item.price} each
                      </p>
                    </div>
                    <div className="quantity-controls">
                      <button
                        onClick={() => decreaseQuantity(item.id)}
                        aria-label={`Decrease ${item.name} quantity`}
                      >
                        −
                      </button>
                      <span>{item.quantity}</span>
                      <button
                        onClick={() => increaseQuantity(item.id)}
                        disabled={item.quantity >= item.stock}
                        aria-label={`Increase ${item.name} quantity`}
                      >
                        +
                      </button>
                    </div>
                    <strong>${(item.price * item.quantity).toFixed(2)}</strong>
                    <button
                      className="remove-button"
                      onClick={() => removeFromCart(item.id)}
                      aria-label={`Remove ${item.name} from cart`}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>

              <div className="cart-page-summary">
                <span>Total</span>
                <strong>${cartTotal.toFixed(2)}</strong>
                <button className="checkout-button">
                  Proceed to Checkout
                </button>
              </div>
            </div>
          ) : (
            <p className="empty-cart">Your cart is empty.</p>
          )}
        </section>
      ) : (
        <>
          <section className="hero">
            <div className="hero-content">
              <p className="hero-label">CURATED FOR MODERN LIVING</p>
              <h1>
                Everything you need.
                <br />
                <span>All in one place.</span>
              </h1>
              <p className="hero-text">
                Discover carefully selected products designed to make everyday
                living simpler and better.
              </p>
              <a href="#shop" className="hero-button">
                Explore Collection
              </a>
            </div>
          </section>

          <section className="category-section" aria-labelledby="category-heading">
            <div className="category-heading">
              <p className="section-label">SHOP BY CATEGORY</p>
              <h2 id="category-heading">Find something made for your everyday</h2>
            </div>
            <div className="category-grid">
              {categoryCards.map(({ name, product }) => (
                <button
                  className={`category-card ${category === name ? "active" : ""}`}
                  key={name}
                  onClick={() => selectCategory(name)}
                  style={product ? { backgroundImage: `url(${getImageUrl(product.image)})` } : undefined}
                >
                  <span className="category-card-overlay" />
                  <span className="category-card-content">
                    <span className="category-card-name">{name}</span>
                    <span className="category-card-description">
                      Thoughtful pieces for modern living.
                    </span>
                    <span className="category-card-link">Explore →</span>
                  </span>
                </button>
              ))}
            </div>
            <button
              className={`all-products-button ${category === "All" ? "active" : ""}`}
              onClick={() => selectCategory("All")}
            >
              All Products
            </button>
          </section>

          <section className="shop-section" id="shop">
            <div className="section-heading">
              <div>
                <p className="section-label">OUR COLLECTION</p>
                <h2>Shop Products</h2>
              </div>
              <div className="search-box">
                <input
                  type="text"
                  placeholder="Search products..."
                  value={search}
                  onChange={(event) => {
                    setProductPage(1);
                    setSearch(event.target.value);
                  }}
                />
              </div>
            </div>

            <div className="categories">
              {categories.map((item) => (
                <button
                  key={item}
                  className={category === item ? "active" : ""}
                  onClick={() => {
                    setProductPage(1);
                    setCategory(item);
                  }}
                >
                  {item}
                </button>
              ))}
            </div>

            <div className="product-grid">
              {filteredProducts.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  getImageUrl={getImageUrl}
                  onSelect={setSelectedProduct}
                  onAddToCart={addToCart}
                />
              ))}
            </div>

            {filteredProducts.length === 0 && (
              <div className="empty-products">
                <h3>No products found</h3>
                <p>Try another search or category.</p>
              </div>
            )}
            {productPageCount > 1 && (
              <div className="pagination">
                <p>
                  Showing {((productPage - 1) * 8) + 1}–
                  {Math.min(productPage * 8, productTotal)} of {productTotal} products
                </p>
                <button
                  disabled={productPage === 1}
                  onClick={() => setProductPage((page) => page - 1)}
                >
                  ← Previous
                </button>
                {Array.from({ length: productPageCount }, (_, index) => index + 1).map(
                  (page) => (
                    <button
                      key={page}
                      className={page === productPage ? "active" : ""}
                      onClick={() => setProductPage(page)}
                    >
                      {page}
                    </button>
                  )
                )}
                <button
                  disabled={productPage === productPageCount}
                  onClick={() => setProductPage((page) => page + 1)}
                >
                  Next →
                </button>
              </div>
            )}
          </section>

          <section className="features" id="features">
            <div className="features-heading">
              <p className="section-label">WHY US</p>
              <h2>Made for a simpler way to shop</h2>
            </div>
            <div className="feature">
              <div className="feature-icon" aria-hidden="true">✦</div>
              <h3>Curated Products</h3>
              <p>Carefully selected products for everyday needs.</p>
            </div>
            <div className="feature">
              <div className="feature-icon" aria-hidden="true">↗</div>
              <h3>Fast Delivery</h3>
              <p>Quick and reliable delivery to your doorstep.</p>
            </div>
            <div className="feature">
              <div className="feature-icon" aria-hidden="true">♡</div>
              <h3>Secure Shopping</h3>
              <p>A simple and secure shopping experience.</p>
            </div>
          </section>

        </>
      )}

      {cartMessage && (
        <div className="cart-toast" role="status">
          {cartMessage}
        </div>
      )}

      {selectedProduct && (
        <div
          className="modal-overlay"
          onClick={() => setSelectedProduct(null)}
        >
          <div
            className="product-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="close-button"
              onClick={() => setSelectedProduct(null)}
            >
              ×
            </button>

            <img
              src={getImageUrl(selectedProduct.image)}
              alt={selectedProduct.name}
            />

            <div className="modal-content">
              <p className="product-category">
                {selectedProduct.category}
              </p>

              <h2>{selectedProduct.name}</h2>

              <p className="modal-price">
                ${selectedProduct.price}
              </p>

              <p>
                High-quality product selected for our modern ecommerce
                collection.
              </p>

              <p className="stock">
                {selectedProduct.stock} units available
              </p>

              <button
                className="modal-cart-button"
                onClick={() => {
                  addToCart(selectedProduct);
                  setSelectedProduct(null);
                }}
              >
                Add to Cart
              </button>
            </div>
          </div>
        </div>
      )}

      <footer id="contact">
        <div className="footer-logo">LUMORA</div>
        <p>Modern products. Simple shopping.</p>
        <div className="footer-details">
          <div>
            <h2>Location</h2>
            <address>Ahmedabad, Gujarat, India</address>
          </div>
          <div>
            <h2>Call Us</h2>
            <a href="tel:+912222233333">+91 22222 33333</a>
          </div>
          <div>
            <h2>Support Hours</h2>
            <p>24/7</p>
          </div>
        </div>
        <p>© 2026 Lumora Ecommerce</p>
      </footer>
    </div>
  );
}

export default App;