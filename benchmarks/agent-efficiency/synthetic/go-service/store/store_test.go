package store

import (
	"example.org/codira-benchmark-service/config"
	"testing"
)

func TestFormat(t *testing.T) {
	value, err := Format("MiXeD", config.Config{Limit: 10, Mode: "lower"})
	if err != nil || value != "mixed" {
		t.Fatal(value, err)
	}
}
