package config

import "strconv"

type Config struct {
	Limit int
	Mode  string
}

func Resolve(env map[string]string, args map[string]string) Config {
	values := map[string]string{"limit": "10", "mode": "upper"}
	for key, value := range env {
		values[key] = value
	}
	for key, value := range args {
		values[key] = value
	}
	limit, _ := strconv.Atoi(values["limit"])
	return Config{Limit: limit, Mode: values["mode"]}
}
