package middlewares

import (
	"VKR_gateway_service/internal/app"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	contextUserIDKey   = "user_id"
	contextRolesKey    = "roles"
	contextAuthUserKey = "auth_user"
)

type authUserProfile struct {
	Email          string   `json:"email"`
	EmailConfirmed bool     `json:"email_confirmed"`
	FirstName      string   `json:"first_name"`
	LastName       string   `json:"last_name"`
	LocaleType     string   `json:"locale_type"`
	Photo          string   `json:"photo"`
	Roles          []string `json:"roles"`
}

// AuthMiddleware validates JWT via external SSO validate endpoint and extracts user_id.
func AuthMiddleware(a *app.App) gin.HandlerFunc {
	return authMiddleware(a, false)
}

// AuthWithRolesMiddleware validates JWT, extracts user_id and fetches roles via /auth/authenticate.
func AuthWithRolesMiddleware(a *app.App) gin.HandlerFunc {
	return authMiddleware(a, true)
}

func RequireAnyRole(allowed ...string) gin.HandlerFunc {
	normalizedAllowed := normalizeRoles(allowed)
	allowedSet := make(map[string]struct{}, len(normalizedAllowed))
	for _, role := range normalizedAllowed {
		allowedSet[role] = struct{}{}
	}

	return func(c *gin.Context) {
		roles := authRoles(c)
		if len(roles) == 0 {
			c.JSON(http.StatusForbidden, gin.H{"error": "role is required"})
			c.Abort()
			return
		}
		for _, role := range roles {
			if _, ok := allowedSet[role]; ok {
				c.Next()
				return
			}
		}
		c.JSON(http.StatusForbidden, gin.H{"error": "insufficient role"})
		c.Abort()
	}
}

func authMiddleware(a *app.App, requireRoles bool) gin.HandlerFunc {
	return func(c *gin.Context) {
		if strings.HasSuffix(c.Request.URL.Path, "/api/auth/validate") {
			c.Next()
			return
		}
		if c.Request.Method == http.MethodOptions {
			c.Next()
			return
		}

		tokenString := c.GetHeader("Authorization")
		if tokenString == "" || !strings.HasPrefix(tokenString, "Bearer ") {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "Token required"})
			c.Abort()
			return
		}
		if a == nil || a.Config == nil || a.Config.SSO_HTTP_URL == "" {
			c.JSON(http.StatusBadGateway, gin.H{"error": "SSO url not configured"})
			c.Abort()
			return
		}

		validateResponse, err := doSSORequest(c, a, "/api/auth/validate", tokenString)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
			c.Abort()
			return
		}
		defer validateResponse.Body.Close()

		if validateResponse.StatusCode != http.StatusOK {
			msg := readSSOError(validateResponse)
			c.JSON(validateResponse.StatusCode, gin.H{"error": msg})
			c.Abort()
			return
		}

		userID, ok := extractUserIDFromHeader(validateResponse.Header)
		if !ok {
			userID, ok = extractUserIDFromToken(tokenString)
		}
		if ok && userID > 0 {
			c.Set(contextUserIDKey, userID)
		}

		if requireRoles {
			profile, statusCode, err := fetchAuthUserProfile(c, a, tokenString)
			if err != nil {
				c.JSON(statusCode, gin.H{"error": err.Error()})
				c.Abort()
				return
			}
			c.Set(contextRolesKey, profile.Roles)
			c.Set(contextAuthUserKey, profile)
		}

		c.Next()
	}
}

func fetchAuthUserProfile(c *gin.Context, a *app.App, tokenString string) (*authUserProfile, int, error) {
	resp, err := doSSORequest(c, a, "/api/auth/authenticate", tokenString)
	if err != nil {
		return nil, http.StatusBadGateway, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, resp.StatusCode, readSSOError(resp)
	}

	var profile authUserProfile
	if err := json.NewDecoder(io.LimitReader(resp.Body, 64*1024)).Decode(&profile); err != nil {
		return nil, http.StatusBadGateway, err
	}
	profile.Roles = normalizeRoles(profile.Roles)
	return &profile, http.StatusOK, nil
}

func doSSORequest(c *gin.Context, a *app.App, path string, tokenString string) (*http.Response, error) {
	target := strings.TrimRight(a.Config.SSO_HTTP_URL, "/") + path
	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodGet, target, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", tokenString)
	req.Header.Set("Accept", "application/json")
	timeout := 5 * time.Second
	if a.Config.GRPCTimeout > 0 {
		timeout = a.Config.GRPCTimeout
	}
	httpClient := &http.Client{Timeout: timeout}
	return httpClient.Do(req)
}

func readSSOError(resp *http.Response) error {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
	if len(body) == 0 {
		return &plainError{message: "request failed"}
	}
	var payload struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(body, &payload); err == nil && strings.TrimSpace(payload.Error) != "" {
		return &plainError{message: strings.TrimSpace(payload.Error)}
	}
	return &plainError{message: strings.TrimSpace(string(body))}
}

type plainError struct {
	message string
}

func (e *plainError) Error() string {
	if e == nil || e.message == "" {
		return "request failed"
	}
	return e.message
}

func authRoles(c *gin.Context) []string {
	value, ok := c.Get(contextRolesKey)
	if !ok {
		return nil
	}
	switch typed := value.(type) {
	case []string:
		return append([]string(nil), typed...)
	case []any:
		out := make([]string, 0, len(typed))
		for _, raw := range typed {
			if role := strings.TrimSpace(strings.ToUpper(toString(raw))); role != "" {
				out = append(out, role)
			}
		}
		return out
	default:
		return nil
	}
}

func normalizeRoles(values []string) []string {
	out := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		role := strings.TrimSpace(strings.ToUpper(value))
		if role == "" {
			continue
		}
		if _, ok := seen[role]; ok {
			continue
		}
		seen[role] = struct{}{}
		out = append(out, role)
	}
	return out
}

func toString(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	default:
		return ""
	}
}

func extractUserID(body []byte) (int64, bool) {
	if len(body) == 0 {
		return 0, false
	}
	var payload interface{}
	if err := json.Unmarshal(body, &payload); err != nil {
		return 0, false
	}
	return findUserIDRecursive(payload)
}

func findUserIDRecursive(payload interface{}) (int64, bool) {
	switch v := payload.(type) {
	case map[string]interface{}:
		keys := []string{"user_id", "userId", "userID", "User_id", "UserId", "id", "uid", "sub"}
		for _, key := range keys {
			if raw, ok := v[key]; ok {
				if id, ok := normalizeID(raw); ok {
					return id, true
				}
			}
		}
		for _, raw := range v {
			if id, ok := findUserIDRecursive(raw); ok {
				return id, true
			}
		}
	case []interface{}:
		for _, raw := range v {
			if id, ok := findUserIDRecursive(raw); ok {
				return id, true
			}
		}
	}
	return 0, false
}

func extractUserIDFromHeader(header http.Header) (int64, bool) {
	keys := []string{"X-User-Id", "X-UserId", "X-UserID"}
	for _, key := range keys {
		value := strings.TrimSpace(header.Get(key))
		if value == "" {
			continue
		}
		id, err := strconv.ParseInt(value, 10, 64)
		if err == nil && id > 0 {
			return id, true
		}
	}
	return 0, false
}

func extractUserIDFromToken(tokenString string) (int64, bool) {
	tokenString = strings.TrimSpace(tokenString)
	if strings.HasPrefix(tokenString, "Bearer ") {
		tokenString = strings.TrimSpace(strings.TrimPrefix(tokenString, "Bearer "))
	}
	parts := strings.Split(tokenString, ".")
	if len(parts) < 2 {
		return 0, false
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return 0, false
	}
	return extractUserID(payload)
}

func normalizeID(v interface{}) (int64, bool) {
	switch t := v.(type) {
	case float64:
		return int64(t), true
	case string:
		id, err := strconv.ParseInt(t, 10, 64)
		if err != nil {
			return 0, false
		}
		return id, true
	case json.Number:
		id, err := t.Int64()
		if err != nil {
			return 0, false
		}
		return id, true
	default:
		return 0, false
	}
}
