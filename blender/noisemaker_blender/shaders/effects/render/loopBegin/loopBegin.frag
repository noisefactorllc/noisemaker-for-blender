#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/**
 * begin - Blend input with accumulator nm_buffer using lighten mode
 *
 * Reads from the shared accumulator nmTex(feedback from previous frame)
 * and blends with the current input using max (lighten) blend mode.
 * The result passes through to the next effect in the chain.
 */

void main() {
    vec2 st = gl_FragCoord.xy / resolution;

    vec4 inputColor = nmTex(inputTex, st);
    vec4 accum = nmTex(accumTex, st);

    // Normalize alpha from 0-100 to 0-1
    float a = alpha / 100.0;

    // Normalize intensity from 0-100 to 0-1
    float i = intensity / 100.0;

    // Lighten blend: max of input and accumulated
    vec4 blended = max(inputColor, accum * i);

    // Mix between pure input and blended based on alpha
    vec4 result = mix(inputColor, blended, a);

    // Preserve alpha
    result.a = max(inputColor.a, accum.a);

    fragColor = result;
}
