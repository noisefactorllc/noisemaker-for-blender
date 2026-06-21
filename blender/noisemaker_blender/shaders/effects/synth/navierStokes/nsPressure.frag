#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/*
 * Navier-Stokes pressure pass (Jacobi iteration).
 * One step of the Jacobi solver for ∇²p = ∇·u. Pressure is in R, divergence in G (preserved
 * across iterations). The runtime ping-pongs the state texture for each repeated invocation.
 */

void main() {
    ivec2 texSize = textureSize(bufTex, 0);
    vec2 fragCoord = gl_FragCoord.xy;
    vec2 texel = 1.0 / vec2(texSize);
    vec2 uv = fragCoord / vec2(texSize);

    float pR = nmTex(bufTex, uv + vec2(texel.x, 0.0)).r;
    float pL = nmTex(bufTex, uv - vec2(texel.x, 0.0)).r;
    float pT = nmTex(bufTex, uv + vec2(0.0, texel.y)).r;
    float pB = nmTex(bufTex, uv - vec2(0.0, texel.y)).r;

    float div = nmTex(bufTex, uv).g;

    float p = (pR + pL + pT + pB - div) * 0.25;

    fragColor = vec4(p, div, 0.0, 1.0);
}
