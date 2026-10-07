package store

import (
	"errors"
	"example.org/codira-benchmark-service/config"
	"strings"
)

func Format(text string, cfg config.Config) (string, error) {
	// Seeded defect: zero should mean unlimited, including an empty value.
	if cfg.Limit <= 0 {
		return "", errors.New("limit must be positive")
	}
	if cfg.Mode == "lower" {
		text = strings.ToLower(text)
	} else {
		text = strings.ToUpper(text)
	}
	if len(text) > cfg.Limit {
		text = text[:cfg.Limit]
	}
	return text, nil
}
