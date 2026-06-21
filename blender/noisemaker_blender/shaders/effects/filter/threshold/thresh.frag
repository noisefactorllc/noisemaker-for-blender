#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/* Binary threshold with adjustable edge softness. */
void main(){
  vec2 globalCoord = gl_FragCoord.xy + tileOffset;
  vec2 st = gl_FragCoord.xy / vec2(textureSize(inputTex,0));
  vec4 c = nmTex(inputTex, st);
  float l = dot(c.rgb, vec3(0.299,0.587,0.114));
  float e = smoothstep(level - sharpness, level + sharpness, l);
  fragColor = vec4(vec3(e),1.0);
}
