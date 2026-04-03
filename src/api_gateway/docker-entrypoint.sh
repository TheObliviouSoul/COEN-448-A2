#!/bin/bash
set -e

# Validate P_VALUE
if [ -z "$P_VALUE" ]; then
    echo "Error: P_VALUE environment variable not set"
    exit 1
fi

echo $P_VALUE

if ! echo "$P_VALUE" | grep -Eq '^[0-9]+([.][0-9]+)?$'; then
    echo "Error: P_VALUE must be numeric"
    exit 1
fi

WEIGHTS=$(awk -v p="$P_VALUE" 'BEGIN {
    if (p < 0 || p > 100) {
        exit 1
    }
    if (p <= 1) {
        v1 = int((p * 100) + 0.5)
    } else {
        v1 = int(p + 0.5)
    }
    v2 = 100 - v1
    printf "%d %d", v1, v2
}')

if [ -z "$WEIGHTS" ]; then
    echo "Error: P_VALUE must be between 0 and 1 or between 0 and 100"
    exit 1
fi

read USER_SERVICE_V1_WEIGHT USER_SERVICE_V2_WEIGHT <<EOF
$WEIGHTS
EOF

if [ "$USER_SERVICE_V1_WEIGHT" -eq 0 ]; then
    USER_SERVICE_TARGETS=$(cat <<EOF
      - target: user-service-v2:5000
        weight: 100
EOF
)
elif [ "$USER_SERVICE_V2_WEIGHT" -eq 0 ]; then
    USER_SERVICE_TARGETS=$(cat <<EOF
      - target: user-service-v1:5000
        weight: 100
EOF
)
else
    USER_SERVICE_TARGETS=$(cat <<EOF
      - target: user-service-v1:5000
        weight: ${USER_SERVICE_V1_WEIGHT}
      - target: user-service-v2:5000
        weight: ${USER_SERVICE_V2_WEIGHT}
EOF
)
fi

export USER_SERVICE_V1_WEIGHT
export USER_SERVICE_V2_WEIGHT
export USER_SERVICE_TARGETS

echo $USER_SERVICE_V1_WEIGHT
echo $USER_SERVICE_V2_WEIGHT

# Replace environment variables in kong.yml.template
envsubst < /etc/kong/kong.yml.template > /etc/kong/kong.yml

cat /etc/kong/kong.yml

# Prepare Kong prefix directory
kong prepare -p /usr/local/kong

# Start Kong
exec kong start --nginx-conf /usr/local/kong/nginx.conf --vv
