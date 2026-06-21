#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/*
 * Cel Shading - Color Pass
 * sRGB-aware color quantization with diffuse shading
 */

const float MIN_GAMMA = 1e-3;

float srgb_to_linear_component(float value) {
    if (value <= 0.04045) {
        return value / 12.92;
    }
    return pow((value + 0.055) / 1.055, 2.4);
}

float linear_to_srgb_component(float value) {
    if (value <= 0.0031308) {
        return value * 12.92;
    }
    return 1.055 * pow(value, 1.0 / 2.4) - 0.055;
}

vec3 srgb_to_linear_rgb(vec3 rgb) {
    return vec3(
        srgb_to_linear_component(rgb.x),
        srgb_to_linear_component(rgb.y),
        srgb_to_linear_component(rgb.z)
    );
}

vec3 linear_to_srgb_rgb(vec3 rgb) {
    return vec3(
        linear_to_srgb_component(rgb.x),
        linear_to_srgb_component(rgb.y),
        linear_to_srgb_component(rgb.z)
    );
}

vec3 pow_vec3(vec3 value, float exponent) {
    return vec3(
        pow(value.x, exponent),
        pow(value.y, exponent),
        pow(value.z, exponent)
    );
}

void main() {
    vec2 globalCoord = gl_FragCoord.xy + tileOffset;
    ivec2 texSize = textureSize(inputTex, 0);
    vec2 uv = gl_FragCoord.xy / vec2(texSize);

    vec4 origColor = nmTex(inputTex, uv);
    float lev = float(levels);

    // Apply diffuse shading based on light direction
    vec3 lightDir = normalize(lightDirection);
    float gradientShade = dot(normalize(vec3(uv - 0.5, 0.5)), lightDir);
    float diffuse = 0.5 + 0.5 * gradientShade;
    float shadeFactor = mix(1.0, 0.5 + 0.5 * diffuse, strength);
    vec3 shadedColor = origColor.rgb * shadeFactor;

    // sRGB-aware quantization
    float gamma_value = max(gamma, MIN_GAMMA);
    float inv_gamma = 1.0 / gamma_value;
    float inv_factor = 1.0 / lev;
    float half_step = inv_factor * 0.5;

    vec3 working_rgb = srgb_to_linear_rgb(shadedColor);
    working_rgb = pow_vec3(clamp(working_rgb, vec3(0.0), vec3(1.0)), gamma_value);

    // Posterize with optional edge smoothing
    vec3 scaled = working_rgb * lev + vec3(half_step);
    vec3 quantized_rgb;
    if (antialias) {
        vec3 f = fract(scaled);
        vec3 fw = fwidth(scaled);
        vec3 blend = smoothstep(0.5 - fw * 0.5, 0.5 + fw * 0.5, f);
        quantized_rgb = (floor(scaled) + blend) * inv_factor;
    } else {
        quantized_rgb = floor(scaled) * inv_factor;
    }
    quantized_rgb = pow_vec3(clamp(quantized_rgb, vec3(0.0), vec3(1.0)), inv_gamma);
    quantized_rgb = linear_to_srgb_rgb(quantized_rgb);

    fragColor = vec4(clamp(quantized_rgb, 0.0, 1.0), origColor.a);
}
