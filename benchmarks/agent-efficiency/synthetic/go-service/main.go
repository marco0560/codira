package main

import (
	"example.org/codira-benchmark-service/config"
	"example.org/codira-benchmark-service/store"
	"fmt"
	"os"
	"strings"
)

func main() {
	args := map[string]string{}
	for _, arg := range os.Args[1:] {
		parts := strings.SplitN(arg, "=", 2)
		if len(parts) == 2 {
			args[parts[0]] = parts[1]
		}
	}
	env := map[string]string{}
	if value, ok := os.LookupEnv("SERVICE_LIMIT"); ok {
		env["limit"] = value
	}
	if value, ok := os.LookupEnv("SERVICE_MODE"); ok {
		env["mode"] = value
	}
	cfg := config.Resolve(env, args)
	value, err := store.Format("MiXeD", cfg)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Println(value)
}
