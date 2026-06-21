/* Produces a nm_constant color with premultiplied alpha. */
void main() {
  // Premultiply RGB by alpha for correct compositing
  fragColor = vec4(color * alpha, alpha);
}
