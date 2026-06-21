#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
// Ridge effect.
// Parameterized ridge transform with configurable midpoint level.

vec4 ridge_transform(vec4 value, float lvl) {
    float denom = max(lvl, 1.0 - lvl);
    vec4 result = vec4(1.0) - abs(value - vec4(lvl)) / denom;
    return clamp(result, vec4(0.0), vec4(1.0));
}

void main() {
    vec2 globalCoord = gl_FragCoord.xy + tileOffset;
    ivec2 dims = textureSize(inputTex, 0);
    vec2 uv = gl_FragCoord.xy / vec2(dims);

    vec4 texel = nmTex(inputTex, uv);

    // Apply ridge transform
    vec4 ridged = ridge_transform(texel, level);
    vec4 out_color = vec4(ridged.xyz, 1.0);

    fragColor = out_color;
}
