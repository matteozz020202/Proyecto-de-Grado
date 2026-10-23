from django import forms
from .models import Court,Venue


class ImageAdminForm(forms.ModelForm):
    remove_image=forms.BooleanField(required=False,label="Eliminar imagen actual")

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._original_image=self.instance.image.name if self.instance.pk and self.instance.image else ""

    def clean_image(self):
        image=self.cleaned_data.get("image")
        upload=self.files.get("image")
        if upload:
            if upload.size>5*1024*1024:
                raise forms.ValidationError("La imagen no puede superar los 5 MB.")
            if upload.content_type not in {"image/jpeg","image/png","image/webp"}:
                raise forms.ValidationError("Solo se permiten imágenes JPG, PNG o WebP.")
        return image

    def clean(self):
        cleaned=super().clean()
        if cleaned.get("remove_image") and self.files.get("image"):
            raise forms.ValidationError("Elige entre cambiar la imagen o eliminar la actual.")
        return cleaned

    def save(self,commit=True):
        instance=super().save(commit=False)
        remove=self.cleaned_data.get("remove_image")
        new_image=bool(self.files.get("image"))

        if remove:
            instance.image=None

        if commit:
            instance.save()
            self._save_m2m()

            if self._original_image and (remove or new_image):
                current=instance.image.name if instance.image else ""
                if current!=self._original_image:
                    self._meta.model._meta.get_field("image").storage.delete(self._original_image)

        return instance


class VenueForm(ImageAdminForm):
    class Meta:
        model=Venue
        fields=["venue_name","city","address","image"]
        labels={
            "venue_name":"Nombre del establecimiento",
            "city":"Ciudad",
            "address":"Dirección",
            "image":"Cambiar imagen"
        }
        widgets={
            "venue_name":forms.TextInput(attrs={"class":"form-control","placeholder":"Nombre del establecimiento"}),
            "city":forms.TextInput(attrs={"class":"form-control","placeholder":"Ciudad"}),
            "address":forms.TextInput(attrs={"class":"form-control","placeholder":"Dirección"}),
            "image":forms.FileInput(attrs={"class":"image-file-input","accept":"image/jpeg,image/png,image/webp"})
        }


class CourtForm(ImageAdminForm):
    class Meta:
        model=Court
        fields=["court_name","price_per_hour","description","image"]
        labels={
            "court_name":"Nombre de la cancha",
            "price_per_hour":"Precio por hora",
            "description":"Descripción",
            "image":"Cambiar imagen"
        }
        widgets={
            "court_name":forms.TextInput(attrs={"class":"form-control","placeholder":"Nombre de la cancha"}),
            "price_per_hour":forms.NumberInput(attrs={"class":"form-control","min":"0","step":"1000"}),
            "description":forms.Textarea(attrs={"class":"form-control","rows":4,"placeholder":"Descripción de la cancha"}),
            "image":forms.FileInput(attrs={"class":"image-file-input","accept":"image/jpeg,image/png,image/webp"})
        }